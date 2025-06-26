# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/codegens/typescript/generator.py
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
    """TypeScript 代码生成器。"""
    def __init__(self, type_system: 'TypeSystem', temp_dir: str, target_config: dict):
        super().__init__(type_system, temp_dir, target_config)
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.target_config["templates_dir"]),
            trim_blocks=True,
            lstrip_blocks=True
        )
        self.jinja_env.filters['camel_case'] = lambda s: inflection.camelize(s, uppercase_first_letter=False)
        self.jinja_env.filters['pascal_case'] = inflection.camelize

    def generate_all(self, tables: list['ConfigTable']):
        """为所有配置表生成 TypeScript 代码的主入口。"""
        index_content = []
        
        # 1. 生成所有表格对应的代码
        for table in tables:
            class_name = inflection.camelize(table.target_type_name)
            file_name = inflection.underscore(class_name)
            
            if table.is_flat_table:
                index_content.append(f'export * from "./{file_name}";')
                self.generate_flat_singleton(table)
            else:
                manager_name = f"{inflection.camelize(table.base_name)}ConfigManager"
                index_content.append(f'export type {{ I{class_name} }} from "./{file_name}";')
                index_content.append(f'export {{ {manager_name} }} from "./{inflection.underscore(manager_name)}";')
                self.generate_standard_table(table)
        
        # 2. 生成 DataReader 辅助类
        self._generate_datareader()
        index_content.append(f'export * from "./data_reader";')
        
        # 3. 写入 index.ts 文件
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, "index.ts")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(index_content))

    def _get_ts_type(self, type_syntax_str: str) -> str:
        """递归地将类型字符串转换为 TypeScript 类型声明。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll == "list" or coll == "array":
            return f"{self._get_ts_type(inner)}[]"
        if coll == "set":
            return f"Set<{self._get_ts_type(inner)}>"
        
        type_name = inner
        if type_name in ['int', 'float']: return 'number'
        if type_name == 'long': return 'bigint'
        if type_name == 'string': return 'string'
        if type_name == 'bool': return 'boolean'
        
        return inflection.camelize(os.path.basename(self.type_system.get_type(type_name).get("TargetType", type_name)))

    def _get_read_info(self, type_syntax_str: str) -> dict:
        """为模板准备一个包含完整读取信息的字典。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            return {"is_collection": True, "type": self._get_ts_type(type_str), "list_item": self._get_read_info(inner)}
        
        is_complex, is_enum = False, False
        try:
            t_def = self.type_system.get_type(type_str)
            is_complex = "FieldSequence" in t_def and not t_def.get("TargetTypeAsEnum")
            is_enum = t_def.get("TargetTypeAsEnum", False)
        except ValueError: pass

        read_method = "getInt32"
        if type_str == "long": read_method = "getBigInt64"
        elif type_str == "string": read_method = "readString"
        elif type_str == "bool": read_method = "getBoolean"
        elif type_str == "float": read_method = "getFloat32"

        return {"is_collection": False, "type": self._get_ts_type(type_str), "is_complex": is_complex, "is_enum": is_enum, "read_method": read_method}

    def _collect_imports_recursive(self, type_syntax_str: str, current_def_target_path: str, imports: dict):
        """递归地收集一个类型所需的所有导入项，并计算正确的相对路径。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            self._collect_imports_recursive(inner, current_def_target_path, imports)
            return

        if inner in ["int", "long", "string", "bool", "float"]: return

        try:
            dep_def = self.type_system.get_type(inner)
            dep_target_path = dep_def.get("TargetType")
            
            is_complex = "FieldSequence" in dep_def and not dep_def.get("TargetTypeAsEnum")
            is_enum = dep_def.get("TargetTypeAsEnum", False)

            if (is_complex or is_enum) and dep_target_path and dep_target_path != current_def_target_path:
                dep_class_name = inflection.camelize(os.path.basename(dep_target_path))
                dep_file_name = inflection.underscore(dep_class_name)
                
                # 规范化路径以进行正确计算
                current_dir = os.path.dirname(current_def_target_path) or '.'
                dep_dir = os.path.dirname(dep_target_path)
                
                relative_dir = os.path.relpath(dep_dir, current_dir).replace('\\', '/').lower()
                
                import_path = f"./{dep_file_name}" if relative_dir == '.' else f"{relative_dir}/{dep_file_name}"
                
                import_name = f"I{dep_class_name}" if is_complex else dep_class_name
                
                if import_path not in imports: imports[import_path] = set()
                imports[import_path].add(import_name)
        except ValueError: pass
    
    def _recursive_dependency_gen(self, type_syntax_str: str):
        """递归地为给定类型及其所有子类型生成代码。"""
        type_str, _ = parse_unified_syntax(type_syntax_str)
        coll, inner = parse_type_string(type_str)
        if coll:
            self._recursive_dependency_gen(inner)
            return
        if inner in ["int", "long", "string", "bool", "float"]: return
        try:
            dep_type_def = self.type_system.get_type(inner)
            if "TargetType" in dep_type_def:
                if self._generate_interface_or_enum(dep_type_def):
                    for field_type_str in dep_type_def.get("FieldTypes", {}).values():
                        self._recursive_dependency_gen(field_type_str)
        except ValueError: pass

    def _generate_interface_or_enum(self, type_def: dict, comments: dict = None, struct_comment: str = "") -> bool:
        """生成单个 interface/class 或 enum 文件。"""
        target_path = type_def.get("TargetType", "")
        is_generatable = "FieldSequence" in type_def or type_def.get("TargetTypeAsEnum")
        if not target_path or not is_generatable: return False

        class_name = inflection.camelize(os.path.basename(target_path))
        filename = f"{inflection.underscore(class_name)}.ts"
        if filename in self.generated_files: return False
            
        sub_path_str = os.path.dirname(target_path)
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'], sub_path_str.lower())
        os.makedirs(output_dir, exist_ok=True)
        comment_purpose = struct_comment or type_def.get("comment", f"Represents a {class_name}.")
        
        # 计算 DataReader 的正确相对路径
        current_dir = sub_path_str or '.'
        root_dir = "" 
        datareader_rel_path = os.path.relpath(root_dir, current_dir).replace('\\', '/')
        datareader_import_path = f"{datareader_rel_path}/data_reader" if datareader_rel_path != '.' else './data_reader'

        imports = {}
        if type_def.get("FieldTypes"):
            for field_type_str in type_def["FieldTypes"].values():
                self._collect_imports_recursive(field_type_str, target_path, imports)
        
        import_statements = [f'import type {{ {", ".join(sorted(list(names)))} }} from "{path}";' for path, names in sorted(imports.items())]

        if type_def.get("TargetTypeAsEnum"):
            template = self.jinja_env.get_template("ts_enum.ts.j2")
            content = template.render(enum_name=class_name, comment_purpose=comment_purpose, members=[{"name": inflection.camelize(k), "value": v, "comment": ""} for k, v in type_def.get("EnumMembers", {}).items()])
        else:
            template = self.jinja_env.get_template("ts_interface.ts.j2")
            fields_data = [{"name": inflection.camelize(name, False), "type": self._get_ts_type(field_type_syntax_str), "comment": (comments or {}).get(name, ""), "read_info": self._get_read_info(field_type_syntax_str)} for name, field_type_syntax_str in type_def.get("FieldTypes", {}).items()]
            content = template.render(class_name=class_name, struct_comment=comment_purpose, datareader_import_path=datareader_import_path, import_statements=import_statements, fields=fields_data)

        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        self.generated_files.add(filename)
        return True

    def _generate_datareader(self):
        filename = "data_reader.ts"
        if filename in self.generated_files: return
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        template = self.jinja_env.get_template("ts_datareader.ts.j2")
        content = template.render()
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
        self.generated_files.add(filename)

    def generate_standard_table(self, table: 'ConfigTable'):
        main_type_def = self.type_system.get_type(table.target_type_name)
        comments = {row.key: row.comment for row in table.rows}
        for row in table.rows: self._recursive_dependency_gen(row.type_syntax)
        self._generate_interface_or_enum(main_type_def, comments, table.table_comment)
        
        manager_name = f"{inflection.camelize(table.base_name)}ConfigManager"
        template = self.jinja_env.get_template("ts_manager.ts.j2")
        content = template.render(manager_name=manager_name, data_class_name=inflection.camelize(table.target_type_name), primary_key_fields=[inflection.camelize(f, False) for f in table.primary_key_fields])
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{inflection.underscore(manager_name)}.ts")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)

    def generate_flat_singleton(self, table: 'ConfigTable'):
        class_name = inflection.camelize(table.target_type_name)
        imports = {}
        for row in table.rows:
            self._recursive_dependency_gen(row.type_syntax)
            self._collect_imports_recursive(row.type_syntax, class_name, imports)

        import_statements = [f'import type {{ {", ".join(sorted(list(names)))} }} from "{path}";' for path, names in sorted(imports.items())]
        fields_data = [{"name": inflection.camelize(row.key, False), "type": self._get_ts_type(row.type_syntax), "comment": row.comment, "read_info": self._get_read_info(row.type_syntax)} for row in table.rows]
        
        template = self.jinja_env.get_template("ts_flat_singleton.ts.j2")
        content = template.render(class_name=class_name, struct_comment=table.table_comment, excel_file_name=table.excel_file_name, import_statements=import_statements, fields=fields_data)
        output_dir = os.path.join(self.temp_dir, self.target_config['output_dir'])
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{inflection.underscore(class_name)}.ts")
        with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
