# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/codegens/javascript/generator.py
import os
from jinja2 import Environment, FileSystemLoader
import inflection

# 动态导入，避免循环依赖并提供类型提示
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...models import ConfigTable
    from ...readers import TypeSystem

from ..base_generator import BaseCodeGenerator
from ...writers import parse_type_string # 复用解析器

class CodeGenerator(BaseCodeGenerator):
    """JavaScript 代码生成器 (使用 JSDoc)。"""
    def __init__(self, type_system: 'TypeSystem', temp_dir: str, target_config: dict):
        super().__init__(type_system, temp_dir, target_config)
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.target_config["templates_dir"]),
            trim_blocks=True, lstrip_blocks=True
        )
        # 为模板添加过滤器
        self.jinja_env.filters['camel_case'] = lambda s: inflection.camelize(s, uppercase_first_letter=False)
        self.jinja_env.filters['pascal_case'] = inflection.camelize

    def generate_all(self, tables: list['ConfigTable']):
        """为所有配置表生成 JavaScript 代码的主入口。"""
        # 生成一个总的 index.js 文件，用于导出所有内容
        index_content = []
        for table in tables:
            if table.is_flat_table:
                class_name = inflection.camelize(table.target_type_name)
                file_name = inflection.underscore(class_name)
                index_content.append(f'export * from "./{file_name}.js";')
                self.generate_flat_singleton(table)
            else:
                manager_name = f"{inflection.camelize(table.base_name)}ConfigManager"
                file_name = inflection.underscore(manager_name)
                index_content.append(f'export * from "./{file_name}.js";')
                self.generate_standard_table(table)
        
        # 写入 index.js 文件
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, "index.js")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(index_content))

    def _get_jsdoc_type(self, type_str: str) -> str:
        """递归地将类型字符串转换为 JSDoc 类型声明。"""
        coll, inner = parse_type_string(type_str)
        if coll == "list" or coll == "array":
            return f"Array<{self._get_jsdoc_type(inner)}>"
        if coll == "set":
            return f"Set<{self._get_jsdoc_type(inner)}>"
        
        type_name = inner
        if type_name in ['int', 'long', 'float']: return 'number'
        if type_name == 'string': return 'string'
        if type_name == 'bool': return 'boolean'
        
        # 对于自定义类型，返回其类名 (PascalCase)
        return inflection.camelize(os.path.basename(self.type_system.get_type(type_name).get("TargetType", type_name)))

    def _get_read_info(self, type_str: str) -> dict:
        """为模板准备一个包含完整读取信息的字典。"""
        coll, inner = parse_type_string(type_str)
        if coll:
            return {"is_collection": True, "type": self._get_jsdoc_type(type_str), "list_item": self._get_read_info(inner)}
        
        is_complex, is_enum = False, False
        try:
            t_def = self.type_system.get_type(type_str)
            is_complex = "/" in t_def.get("TargetType", "") and not t_def.get("TargetTypeAsEnum")
            is_enum = t_def.get("TargetTypeAsEnum", False)
        except ValueError: pass

        # 映射到 DataView 的方法
        read_method = "getInt32"
        if type_str == "long": read_method = "getBigInt64"
        elif type_str == "string": read_method = "readString" # 这是个自定义的辅助函数
        elif type_str == "bool": read_method = "getBoolean"
        elif type_str == "float": read_method = "getFloat32"

        return {"is_collection": False, "type": self._get_jsdoc_type(type_str), "is_complex": is_complex, "is_enum": is_enum, "read_method": read_method}

    def _recursive_dependency_gen(self, type_str: str):
        """递归地为给定类型及其所有子类型生成代码。"""
        coll, inner = parse_type_string(type_str)
        if coll: self._recursive_dependency_gen(inner); return
        if inner in ["int", "long", "string", "bool", "float"]: return
        
        try:
            dep_type_def = self.type_system.get_type(inner)
            if "TargetType" in dep_type_def and "/" in dep_type_def["TargetType"]:
                if self._generate_class_or_enum(dep_type_def):
                    for field_type_str in dep_type_def.get("FieldTypes", {}).values():
                        self._recursive_dependency_gen(field_type_str)
        except ValueError: pass

    def _generate_class_or_enum(self, type_def: dict, comments: dict = None) -> bool:
        """生成单个 class 或 enum 对象，如果尚未生成过。"""
        target_path = type_def.get("TargetType", "")
        class_name = inflection.camelize(os.path.basename(target_path))
        filename = f"{inflection.underscore(class_name)}.js"
        
        if not target_path or "/" not in target_path or filename in self.generated_files: return False
            
        sub_path_str = os.path.dirname(target_path)
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], sub_path_str.lower())
        os.makedirs(output_dir, exist_ok=True)
        
        if type_def.get("TargetTypeAsEnum"):
            template = self.jinja_env.get_template("js_enum.js.j2")
            content = template.render(
                enum_name=class_name,
                members=[{"name": inflection.camelize(k), "value": v} for k, v in type_def.get("EnumMembers", {}).items()]
            )
        else: # 是一个 class
            template = self.jinja_env.get_template("js_class.js.j2")
            fields_data = []
            for name in type_def.get("FieldSequence", []):
                field_type_str = type_def["FieldTypes"][name]
                fields_data.append({
                    "name": inflection.camelize(name, False),
                    "type": self._get_jsdoc_type(field_type_str),
                    "comment": (comments or {}).get(name, ""),
                    "read_info": self._get_read_info(field_type_str)
                })
            content = template.render(
                class_name=class_name,
                fields=fields_data
            )

        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        self.generated_files.add(filename)
        return True

    def generate_standard_table(self, table: 'ConfigTable'):
        """为标准表格生成主 class、依赖和管理器。"""
        main_type_def = self.type_system.get_type(table.target_type_name)
        main_type_def["FieldTypes"] = {row.key: row.type_syntax for row in table.rows}
        main_type_def["FieldSequence"] = [row.key for row in table.rows]
        comments = {row.key: row.comment for row in table.rows}
        
        for field_type_str in main_type_def["FieldTypes"].values(): self._recursive_dependency_gen(field_type_str)
        self._generate_class_or_enum(main_type_def, comments)
        
        manager_name = f"{inflection.camelize(table.base_name)}ConfigManager"
        template = self.jinja_env.get_template("js_manager.js.j2")
        content = template.render(
            manager_name=manager_name,
            data_class_name=inflection.camelize(table.target_type_name),
            primary_key_fields=[inflection.camelize(f, False) for f in table.primary_key_fields],
            read_info=self._get_read_info(table.target_type_name)
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{inflection.underscore(manager_name)}.js")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)

    def generate_flat_singleton(self, table: 'ConfigTable'):
        """为平铺式表格生成单例对象及其依赖。"""
        class_name = inflection.camelize(table.target_type_name)
        
        for row in table.rows: self._recursive_dependency_gen(row.type_syntax)
        
        fields_data = []
        for row in table.rows:
            fields_data.append({
                "name": inflection.camelize(row.key, False),
                "type": self._get_jsdoc_type(row.type_syntax),
                "comment": row.comment,
                "read_info": self._get_read_info(row.type_syntax)
            })
        
        template = self.jinja_env.get_template("js_flat_singleton.js.j2")
        content = template.render(
            class_name=class_name,
            excel_file_name=table.excel_file_name,
            fields=fields_data
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{inflection.underscore(class_name)}.js")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
