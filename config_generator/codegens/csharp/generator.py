# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/codegens/csharp/generator.py
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
    """C# 代码生成器。"""
    def __init__(self, type_system: 'TypeSystem', temp_dir: str, target_config: dict):
        super().__init__(type_system, temp_dir, target_config)
        # 初始化 Jinja2 环境，指向 C# 的模板目录
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.target_config["templates_dir"]),
            trim_blocks=False,
            lstrip_blocks=False
        )
        self.jinja_env.filters['pascal_case'] = inflection.camelize
        self.jinja_env.filters['camel_case'] = lambda s: inflection.camelize(s, uppercase_first_letter=False)

    def generate_all(self, tables: list['ConfigTable']):
        """为所有配置表生成 C# 代码的主入口。"""
        # 首先确保 DataReader 辅助类被生成
        self._generate_datareader()

        for table in tables:
            if table.is_flat_table:
                self.generate_flat_singleton(table)
            else:
                self.generate_standard_table(table)
    
    def _get_csharp_type(self, type_syntax_str: str) -> str:
        """递归地将类型字符串转换为 C# 类型声明。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll == "list":
            return f"System.Collections.Generic.List<{self._get_csharp_type(inner)}>"
        if coll == "array":
            return f"{self._get_csharp_type(inner)}[]"
        if coll == "set":
            return f"System.Collections.Generic.HashSet<{self._get_csharp_type(inner)}>"
        
        type_name = inner
        if type_name in ['long', 'int', 'string', 'bool', 'float']:
            return type_name
            
        return os.path.basename(self.type_system.get_type(type_name).get("TargetType", type_name))

    def _get_read_info(self, type_syntax_str: str) -> dict:
        """为模板准备一个包含完整读取信息的字典，支持递归。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            return {
                "is_collection": True,
                "collection_type": coll,
                "type": self._get_csharp_type(type_str),
                "list_item": self._get_read_info(inner)
            }
        
        is_complex, is_enum = False, False
        try:
            t_def = self.type_system.get_type(type_str)
            is_complex = "FieldSequence" in t_def and not t_def.get("TargetTypeAsEnum")
            is_enum = t_def.get("TargetTypeAsEnum", False)
        except ValueError:
            pass

        # 映射到我们自定义的 DataReader 的方法
        read_method = "ReadInt32()"
        if type_str == "long": read_method = "ReadInt64()"
        elif type_str == "string": read_method = "ReadString()"
        elif type_str == "bool": read_method = "ReadBoolean()"
        elif type_str == "float": read_method = "ReadSingle()"
        
        return {
            "is_collection": False, "type": self._get_csharp_type(type_str),
            "is_complex": is_complex, "is_enum": is_enum, "read_method": read_method
        }

    def _collect_imports_recursive(self, type_syntax_str: str, current_namespace: str, imports: set):
        """递归地为一个类型收集所有必要的 `using` 命名空间。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            self._collect_imports_recursive(inner, current_namespace, imports)
            return
        if inner in ["int", "long", "string", "bool", "float"]:
            return
        try:
            dep_def = self.type_system.get_type(inner)
            dep_target_path = dep_def.get("TargetType")
            if "FieldSequence" in dep_def or dep_def.get("TargetTypeAsEnum"):
                dep_sub_path = os.path.dirname(dep_target_path)
                if dep_sub_path:
                    dep_namespace = self.target_config['namespace'] + "." + dep_sub_path.replace('/', '.')
                    if dep_namespace != current_namespace:
                        imports.add(dep_namespace)
        except ValueError:
            pass

    def _recursive_dependency_gen(self, type_syntax_str: str):
        """递归地为给定类型及其所有子类型生成代码。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            self._recursive_dependency_gen(inner)
            return
        if inner in ["int", "long", "string", "bool", "float"]:
            return
        try:
            dep_type_def = self.type_system.get_type(inner)
            if "TargetType" in dep_type_def:
                if self._generate_class_or_enum(dep_type_def):
                    for field_def in dep_type_def.get("FieldSequence", []):
                        self._recursive_dependency_gen(field_def["Type"])
        except ValueError:
            pass

    def _generate_class_or_enum(self, type_def: dict, struct_comment: str = "") -> bool:
        """
        生成单个类或枚举文件，如果尚未生成过。
        """
        target_path = type_def.get("TargetType", "")
        is_generatable = "FieldSequence" in type_def or type_def.get("TargetTypeAsEnum")
        if not target_path or not is_generatable:
            return False

        class_name = os.path.basename(target_path)
        filename = f"{class_name}.cs"
        if filename in self.generated_files:
            return False
            
        namespace = self.target_config['namespace']
        sub_path_str = os.path.dirname(target_path)
        if sub_path_str:
            namespace += "." + sub_path_str.replace('/', '.')
        
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], sub_path_str)
        os.makedirs(output_dir, exist_ok=True)
        
        comment_purpose = struct_comment or type_def.get("Comment", f"Represents a {class_name}.")
        
        imports = set()
        if type_def.get("FieldSequence"):
            for field_def in type_def.get("FieldSequence", []):
                self._collect_imports_recursive(field_def["Type"], namespace, imports)
        
        if type_def.get("TargetTypeAsEnum"):
            template = self.jinja_env.get_template("csharp_enum.cs.j2")
            content = template.render(
                namespace=namespace, enum_name=class_name,
                comment_purpose=comment_purpose,
                members=[{"name": inflection.camelize(k), "value": v} for k, v in type_def.get("EnumMembers", {}).items()]
            )
        else: # 是一个类
            template = self.jinja_env.get_template("csharp_class.cs.j2")
            fields_data = []
            for field_def in type_def.get("FieldSequence", []):
                fields_data.append({
                    "name": inflection.camelize(field_def["Field"]),
                    "type": self._get_csharp_type(field_def["Type"]),
                    "comment": field_def.get("Comment", ""),
                    "read_info": self._get_read_info(field_def["Type"])
                })
            content = template.render(
                namespace=namespace, class_name=class_name,
                struct_comment=comment_purpose, fields=fields_data,
                imports=sorted(list(imports))
            )
        
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
        self.generated_files.add(filename)
        return True

    def _generate_datareader(self):
        """生成 DataReader 辅助类。"""
        filename = "DataReader.cs"
        if filename in self.generated_files: return
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        template = self.jinja_env.get_template("csharp_datareader.cs.j2")
        content = template.render(namespace=self.target_config['namespace'])
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        self.generated_files.add(filename)

    def generate_standard_table(self, table: 'ConfigTable'):
        """为标准表格生成主类、依赖和管理器。"""
        main_type_def = self.type_system.get_type(table.target_type_name)
        
        for row in table.rows:
            self._recursive_dependency_gen(row.type_syntax)
            
        self._generate_class_or_enum(main_type_def, struct_comment=table.table_comment)
        
        manager_name = f"{table.base_name}ConfigManager"
        template = self.jinja_env.get_template("csharp_manager.cs.j2")
        content = template.render(
            namespace=self.target_config['namespace'], manager_name=manager_name,
            data_class_name=table.target_type_name,
            primary_key_fields=[inflection.camelize(f) for f in table.primary_key_fields]
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{manager_name}.cs")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def generate_flat_singleton(self, table: 'ConfigTable'):
        """为平铺式表格生成单例类及其依赖。"""
        class_name = table.target_type_name
        
        for row in table.rows:
            self._recursive_dependency_gen(row.type_syntax)
        
        imports = set()
        for row in table.rows:
            self._collect_imports_recursive(row.type_syntax, self.target_config['namespace'], imports)

        fields_data = [
            {
                "name": inflection.camelize(row.key),
                "type": self._get_csharp_type(row.type_syntax),
                "comment": row.comment,
                "read_info": self._get_read_info(row.type_syntax),
                "is_collection": parse_type_string(parse_unified_syntax(row.type_syntax)[0])[0] is not None,
                "is_primitive": parse_unified_syntax(row.type_syntax)[0] in ["int","long","string","bool","float"]
            } 
            for row in table.rows
        ]
        
        template = self.jinja_env.get_template("csharp_flat_singleton.cs.j2")
        content = template.render(
            namespace=self.target_config['namespace'], class_name=class_name,
            struct_comment=table.table_comment, excel_file_name=table.excel_file_name,
            fields=fields_data, imports=sorted(list(imports))
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{class_name}.cs")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
