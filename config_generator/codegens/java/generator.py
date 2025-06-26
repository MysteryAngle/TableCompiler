# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/codegens/java/generator.py
import os
from jinja2 import Environment, FileSystemLoader
import inflection

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...models import ConfigTable
    from ...readers import TypeSystem

from ..base_generator import BaseCodeGenerator
from ...writers import parse_type_string, parse_unified_syntax

class CodeGenerator(BaseCodeGenerator):
    """Java 代码生成器。"""
    def __init__(self, type_system: 'TypeSystem', temp_dir: str, target_config: dict):
        super().__init__(type_system, temp_dir, target_config)
        self.jinja_env = Environment(loader=FileSystemLoader(self.target_config["templates_dir"]), trim_blocks=True, lstrip_blocks=True)
        self.jinja_env.filters['pascal_case'] = inflection.camelize
        self.jinja_env.filters['camel_case'] = lambda s: inflection.camelize(s, uppercase_first_letter=False)

    def generate_all(self, tables: list['ConfigTable']):
        for table in tables:
            if table.is_flat_table:
                self.generate_flat_singleton(table)
            else:
                self.generate_standard_table(table)
    
    def _get_java_type(self, type_syntax_str: str) -> str:
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll == "list": return f"java.util.List<{self._get_java_type_wrapper(inner)}>"
        if coll == "array": return f"{self._get_java_type(inner)}[]"
        if coll == "set": return f"java.util.Set<{self._get_java_type_wrapper(inner)}>"
        return self._get_java_type_primitive(inner)
    
    def _get_java_type_primitive(self, type_name: str) -> str:
        """获取 Java 的基本类型或类名。"""
        if type_name == 'int': return 'int'
        if type_name == 'long': return 'long'
        if type_name == 'string': return 'String'
        if type_name == 'bool': return 'boolean'
        if type_name == 'float': return 'float'
        return os.path.basename(self.type_system.get_type(type_name).get("TargetType", type_name))

    def _get_java_type_wrapper(self, type_name: str) -> str:
        """获取 Java 的包装类型或类名，用于泛型。"""
        if type_name == 'int': return 'Integer'
        if type_name == 'long': return 'Long'
        if type_name == 'string': return 'String'
        if type_name == 'bool': return 'Boolean'
        if type_name == 'float': return 'Float'
        return os.path.basename(self.type_system.get_type(type_name).get("TargetType", type_name))

    def _get_read_info(self, type_syntax_str: str) -> dict:
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            return {"is_list": True, "type": self._get_java_type(type_str), "list_item": self._get_read_info(inner)}
        is_complex, is_enum = False, False
        try:
            t_def = self.type_system.get_type(type_str)
            is_complex = "FieldSequence" in t_def and not t_def.get("TargetTypeAsEnum")
            is_enum = t_def.get("TargetTypeAsEnum", False)
        except ValueError: pass
        read_method = "readInt()"
        if type_str == "long": read_method = "readLong()"
        elif type_str == "string": read_method = "readUTF()"
        elif type_str == "bool": read_method = "readBoolean()"
        elif type_str == "float": read_method = "readFloat()"
        return {"is_list": False, "type": self._get_java_type(type_str), "is_complex": is_complex, "is_enum": is_enum, "read_method": read_method}

    def _recursive_dependency_gen(self, type_syntax_str: str):
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll: self._recursive_dependency_gen(inner); return
        if inner in ["int", "long", "string", "bool", "float"]: return
        try:
            dep_type_def = self.type_system.get_type(inner)
            if "TargetType" in dep_type_def:
                if self._generate_class_or_enum(dep_type_def):
                    for field_type_str in dep_type_def.get("FieldTypes", {}).values():
                        self._recursive_dependency_gen(field_type_str)
        except ValueError: pass

    def _generate_class_or_enum(self, type_def: dict, comments: dict = None, struct_comment: str = "") -> bool:
        target_path = type_def.get("TargetType", "")
        is_generatable = "FieldSequence" in type_def or type_def.get("TargetTypeAsEnum")
        if not target_path or not is_generatable: return False
        class_name = os.path.basename(target_path)
        filename = f"{class_name}.java"
        if filename in self.generated_files: return False
        base_package = self.target_config['package']
        sub_path_str = os.path.dirname(target_path)
        package_name = base_package
        if sub_path_str: package_name += "." + sub_path_str.replace('/', '.')
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], base_package.replace('.', '/'), sub_path_str)
        os.makedirs(output_dir, exist_ok=True)
        comment_purpose = struct_comment or type_def.get("comment", f"Represents a {class_name}.")
        if type_def.get("TargetTypeAsEnum"):
            template = self.jinja_env.get_template("java_enum.java.j2")
            content = template.render(package_name=package_name, enum_name=class_name, comment_purpose=comment_purpose, members=[{"name": inflection.underscore(k).upper(), "value": v} for k, v in type_def.get("EnumMembers", {}).items()])
        else:
            template = self.jinja_env.get_template("java_class.java.j2")
            fields_data = []
            for name in type_def.get("FieldSequence", []):
                field_type_syntax_str = type_def["FieldTypes"][name]
                fields_data.append({
                    "name": inflection.camelize(name, False),
                    "pascal_name": inflection.camelize(name), # 新增：为 getter 提供 PascalCase 名称
                    "type": self._get_java_type(field_type_syntax_str),
                    "comment": (comments or {}).get(name, ""),
                    "read_info": self._get_read_info(field_type_syntax_str)
                })
            content = template.render(package_name=package_name, class_name=class_name, struct_comment=comment_purpose, fields=fields_data)
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        self.generated_files.add(filename)
        return True

    def generate_standard_table(self, table: 'ConfigTable'):
        main_type_def = self.type_system.get_type(table.target_type_name)
        comments = {row.key: row.comment for row in table.rows}
        for row in table.rows: self._recursive_dependency_gen(row.type_syntax)
        self._generate_class_or_enum(main_type_def, comments, table.table_comment)
        manager_name = f"{table.base_name}ConfigManager"
        template = self.jinja_env.get_template("java_manager.java.j2")
        content = template.render(
            package_name=self.target_config['package'], manager_name=manager_name,
            data_class_name=table.target_type_name,
            primary_key_fields=[inflection.camelize(f) for f in table.primary_key_fields] # 修正: 传递 PascalCase 名称
        )
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], self.target_config['package'].replace('.', '/'))
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{manager_name}.java")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)

    def generate_flat_singleton(self, table: 'ConfigTable'):
        class_name = table.target_type_name
        for row in table.rows: self._recursive_dependency_gen(row.type_syntax)
        fields_data = []
        for row in table.rows:
            fields_data.append({
                "name": inflection.camelize(row.key, False),
                "pascal_name": inflection.camelize(row.key), # 新增
                "type": self._get_java_type(row.type_syntax),
                "comment": row.comment,
                "read_info": self._get_read_info(row.type_syntax)
            })
        template = self.jinja_env.get_template("java_flat_singleton.java.j2")
        content = template.render(package_name=self.target_config['package'], class_name=class_name, struct_comment=table.table_comment, excel_file_name=table.excel_file_name, fields=fields_data)
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], self.target_config['package'].replace('.', '/'))
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{class_name}.java")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
