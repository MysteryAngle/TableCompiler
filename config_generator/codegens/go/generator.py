# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/codegens/go/generator.py
import os
from jinja2 import Environment, FileSystemLoader
import inflection

# 动态导入，避免循环依赖并提供类型提示
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...models import ConfigTable
    from ...readers import TypeSystem

from ..base_generator import BaseCodeGenerator
from ...writers import parse_type_string, parse_unified_syntax

class CodeGenerator(BaseCodeGenerator):
    """Go 代码生成器。"""
    def __init__(self, type_system: 'TypeSystem', temp_dir: str, target_config: dict):
        super().__init__(type_system, temp_dir, target_config)
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.target_config["templates_dir"]),
            trim_blocks=False, lstrip_blocks=True
        )
        self.jinja_env.filters['pascal_case'] = inflection.camelize
        self.jinja_env.filters['camel_case'] = lambda s: inflection.camelize(s, uppercase_first_letter=False)

    def generate_all(self, tables: list['ConfigTable']):
        """为所有配置表生成 Go 代码的主入口。"""
        for table in tables:
            if table.is_flat_table:
                self.generate_flat_singleton(table)
            else:
                self.generate_standard_table(table)
    
    def _get_go_type(self, type_syntax_str: str, for_declaration: bool = True) -> str:
        """递归地将类型字符串转换为 Go 类型声明。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)

        if coll in ["list", "array"]:
            return f"[]{self._get_go_type(inner, for_declaration)}"
        if coll == "set":
            return f"map[{self._get_go_type(inner, for_declaration)}]struct{{}}"
        
        type_name = inner
        if type_name == 'int': return 'int32'
        if type_name == 'long': return 'int64'
        if type_name == 'string': return 'string'
        if type_name == 'bool': return 'bool'
        if type_name == 'float': return 'float32'
        
        class_name = inflection.camelize(os.path.basename(self.type_system.get_type(type_name).get("TargetType", type_name)))
        
        # 在声明结构体字段时，自定义类型通常使用指针以避免值拷贝
        is_enum = self.type_system.get_type(type_name).get("TargetTypeAsEnum", False)
        if for_declaration and not is_enum:
            return f"*{class_name}"
        return class_name

    def _get_read_info(self, type_syntax_str: str) -> dict:
        """为模板准备一个包含完整读取信息的字典。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            return {"is_collection": True, "type": self._get_go_type(type_str), "list_item": self._get_read_info(inner)}
        
        is_complex, is_enum = False, False
        try:
            t_def = self.type_system.get_type(type_str)
            is_complex = "FieldSequence" in t_def and not t_def.get("TargetTypeAsEnum")
            is_enum = t_def.get("TargetTypeAsEnum", False)
        except ValueError: pass

        return {"is_collection": False, "type": self._get_go_type(type_str), "is_complex": is_complex, "is_enum": is_enum}

    def _recursive_dependency_gen(self, type_syntax_str: str):
        """递归地为给定类型及其所有子类型生成代码。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll: self._recursive_dependency_gen(inner); return
        if inner in ["int", "long", "string", "bool", "float"]: return
        
        try:
            dep_type_def = self.type_system.get_type(inner)
            if "TargetType" in dep_type_def:
                if self._generate_struct_or_enum(dep_type_def):
                    for field_type_str in dep_type_def.get("FieldTypes", {}).values():
                        self._recursive_dependency_gen(field_type_str)
        except ValueError: pass

    def _generate_struct_or_enum(self, type_def: dict, comments: dict = None, struct_comment: str = "") -> bool:
        """生成单个 struct 或 enum 文件，如果尚未生成过。"""
        target_path = type_def.get("TargetType", "")
        is_generatable = "FieldSequence" in type_def or type_def.get("TargetTypeAsEnum")
        if not target_path or not is_generatable: return False

        class_name = inflection.camelize(os.path.basename(target_path))
        filename = f"{inflection.underscore(class_name)}.go"
        if filename in self.generated_files: return False
            
        sub_path_str = os.path.dirname(target_path)
        package_name = os.path.basename(sub_path_str).lower() if sub_path_str else self.target_config['package']
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], sub_path_str.lower())
        os.makedirs(output_dir, exist_ok=True)
        comment_purpose = struct_comment or type_def.get("comment", f"Represents the '{class_name}' type.")

        if type_def.get("TargetTypeAsEnum"):
            template = self.jinja_env.get_template("go_enum.go.j2")
            content = template.render(
                package_name=package_name, enum_name=class_name, comment_purpose=comment_purpose,
                enum_base_type=self._get_go_type('int'),
                members=[{"name": inflection.camelize(k), "value": v} for k, v in type_def.get("EnumMembers", {}).items()]
            )
        else:
            template = self.jinja_env.get_template("go_struct.go.j2")
            fields_data = []
            for name in type_def.get("FieldSequence", []):
                field_type_syntax_str = type_def["FieldTypes"][name]
                fields_data.append({
                    "name": inflection.camelize(name),
                    "json_name": inflection.camelize(name, False),
                    "type": self._get_go_type(field_type_syntax_str),
                    "comment": (comments or {}).get(name, ""),
                    "read_info": self._get_read_info(field_type_syntax_str)
                })
            content = template.render(
                package_name=package_name, class_name=class_name,
                struct_comment=comment_purpose, fields=fields_data
            )

        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        self.generated_files.add(filename)
        return True

    def generate_standard_table(self, table: 'ConfigTable'):
        """为标准表格生成主 struct、依赖和管理器。"""
        main_type_def = self.type_system.get_type(table.target_type_name)
        comments = {row.key: row.comment for row in table.rows}
        
        for row in table.rows:
            self._recursive_dependency_gen(row.type_syntax)
        self._generate_struct_or_enum(main_type_def, comments, table.table_comment)
        
        manager_name = f"{inflection.camelize(table.base_name)}ConfigManager"
        template = self.jinja_env.get_template("go_manager.go.j2")
        content = template.render(
            package_name=self.target_config['package'], manager_name=manager_name,
            data_class_name=inflection.camelize(table.target_type_name),
            primary_key_fields=[inflection.camelize(f) for f in table.primary_key_fields]
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{inflection.underscore(table.base_name)}_manager.go")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)

    def generate_flat_singleton(self, table: 'ConfigTable'):
        """为平铺式表格生成单例 struct 及其依赖。"""
        class_name = inflection.camelize(table.target_type_name)
        
        for row in table.rows:
            self._recursive_dependency_gen(row.type_syntax)
        
        fields_data = []
        for row in table.rows:
            fields_data.append({
                "name": inflection.camelize(row.key),
                "json_name": inflection.camelize(row.key, False),
                "type": self._get_go_type(row.type_syntax),
                "comment": row.comment,
                "read_info": self._get_read_info(row.type_syntax)
            })
        
        template = self.jinja_env.get_template("go_flat_singleton.go.j2")
        content = template.render(
            package_name=self.target_config['package'], class_name=class_name,
            struct_comment=table.table_comment, excel_file_name=table.excel_file_name,
            fields=fields_data
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{inflection.underscore(table.base_name)}.go")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
