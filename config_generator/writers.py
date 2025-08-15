# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/writers.py
import struct
import json
import re
from collections import deque
from .models import ConfigTable

# 用于解析统一类型语法，例如 'list(Item)["~", "#"]'
UNIFIED_TYPE_SYNTAX_REGEX = re.compile(r"^(.*?)(\[.*\])?$")
# 用于解析集合类型，例如 list(Item)
TYPE_STRING_REGEX = re.compile(r"^(list|set|array)\((.*)\)$")

class BinaryWriter:
    """一个将基元类型写入字节数组的辅助类。"""
    def __init__(self):
        self.buffer = bytearray()

    def write_bool(self, v: bool):
        """将布尔值作为1个字节写入。"""
        self.buffer += struct.pack('?', bool(v))

    def write_int(self, v: int):
        """将整数作为4字节的小端序整数写入。"""
        self.buffer += struct.pack('<i', int(v) if v is not None else 0)

    def write_long(self, v: int):
        """将长整数作为8字节的小端序整数写入。"""
        self.buffer += struct.pack('<q', int(v) if v is not None else 0)

    def write_float(self, v: float):
        """将浮点数作为4字节浮点数写入。"""
        self.buffer += struct.pack('<f', float(v) if v is not None else 0.0)

    def write_string(self, v: str):
        """
        写入字符串。首先写入其UTF-8编码的字节长度（4字节整数），
        然后写入实际的编码后字节。
        """
        if v is None:
            self.write_int(0)
            return
        encoded_bytes = str(v).encode('utf-8')
        self.write_int(len(encoded_bytes))
        self.buffer += encoded_bytes

class LayoutWriter:
    """一个将二进制布局结构写入文本的辅助类，用于调试。"""
    def __init__(self):
        self.lines = []
        self.indent_level = 0

    def _indent(self) -> str:
        return "  " * self.indent_level

    def log(self, type_name: str, field_name: str, value: any):
        """记录一条布局信息。"""
        value_str = repr(value)
        if len(value_str) > 100:
            value_str = value_str[:100] + "..."
        self.lines.append(f"{self._indent()}[{type_name}] {field_name} = {value_str}\n")

    def enter_scope(self, scope_name: str):
        """进入一个新的数据范围（如类或列表），增加缩进。"""
        self.lines.append(f"{self._indent()}{scope_name} {{\n")
        self.indent_level += 1

    def exit_scope(self):
        """退出当前数据范围，减少缩进。"""
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}}\n")
        
    def get_content(self) -> str:
        """获取完整的布局文本内容。"""
        return "".join(self.lines)

def parse_type_string(type_str: str):
    """解析集合类型字符串，如 'list(Item)'。"""
    if not isinstance(type_str, str):
        return None, type_str
    match = TYPE_STRING_REGEX.match(type_str.strip())
    if match:
        return match.group(1), match.group(2)
    return None, type_str

def parse_unified_syntax(type_syntax_str: str):
    """解析统一的类型语法，例如 'list(Item)["~", "#"]'。"""
    if not isinstance(type_syntax_str, str):
        return type_syntax_str, None
    match = UNIFIED_TYPE_SYNTAX_REGEX.match(type_syntax_str.strip())
    if not match:
        return type_syntax_str, None
    main_type, delimiters_str = match.group(1).strip(), match.group(2)
    if delimiters_str:
        try:
            return main_type, json.loads(delimiters_str)
        except json.JSONDecodeError:
            raise ValueError(f"类型字符串中的分隔符格式无效: {delimiters_str}。")
    return main_type, None

class CustomBinaryDataHandler:
    """
    负责将 Excel 数据解析并写入自定义二进制格式和布局文本。
    """
    def __init__(self, type_system, writer: BinaryWriter, layout_writer: LayoutWriter):
        self.type_system = type_system
        self.writer = writer
        self.layout_writer = layout_writer

    def write_value(self, raw_value, type_syntax_str: str, context: dict):
        """
        写入单个值的主入口。它负责准备初始数据和解析规则队列。
        """
        if raw_value is None or raw_value == '':
            raw_value = None
        
        type_str, delimiters = parse_unified_syntax(type_syntax_str)
        
        # 优先使用显式定义的分隔符，否则查找默认模式
        if delimiters is None:
            default_schema = self.type_system.get_default_schema(type_str)
            if default_schema:
                delimiters = default_schema.get("string_delimiters")
        
        delimiters_queue = deque(delimiters) if delimiters else deque()
        
        # 如果没有分隔符规则，但值是 JSON 字符串，则预解析它
        if not delimiters and isinstance(raw_value, str) and raw_value.strip().startswith(('{', '[')):
            try:
                raw_value = json.loads(raw_value)
            except json.JSONDecodeError:
                pass # 如果不是合法的JSON，则保持其字符串形式

        self._write_recursive(raw_value, type_str, context.get('col', 'N/A'), delimiters_queue)

    def _write_recursive(self, data, type_str: str, field_name: str, delimiters: deque):
        """根据类型字符串，递归地写入数据，并在需要时消耗分隔符。"""
        collection_type, inner_type_str = parse_type_string(type_str)
        
        if collection_type:
            items = []
            if isinstance(data, str) and delimiters:
                delimiter = delimiters.popleft()
                items = data.split(delimiter) if data else []
            elif isinstance(data, list):
                items = data

            self.writer.write_int(len(items))
            self.layout_writer.log("int", f"{field_name}_count", len(items))
            self.layout_writer.enter_scope(f"{field_name}: {type_str}")
            for i, item in enumerate(items):
                self._write_recursive(item, inner_type_str, f"[{i}]", delimiters.copy())
            self.layout_writer.exit_scope()
            return
            
        name = type_str
        if name == "string":
            self.writer.write_string(data)
            self.layout_writer.log("string", field_name, data)
        elif name == "int":
            self.writer.write_int(data)
            self.layout_writer.log("int", field_name, data)
        elif name == "long":
            self.writer.write_long(data)
            self.layout_writer.log("long", field_name, data)
        elif name == "bool":
            bool_val = str(data).lower() in ['true', '1', 'yes'] if isinstance(data, str) else bool(data)
            self.writer.write_bool(bool_val)
            self.layout_writer.log("bool", field_name, bool_val)
        elif name == "float":
            self.writer.write_float(data)
            self.layout_writer.log("float", field_name, data)
        else:
            type_def = self.type_system.get_type(name)
            if type_def.get("TargetTypeAsEnum"):
                enum_val = 0
                if data is not None:
                    if isinstance(data, int):
                        enum_val = data
                    elif isinstance(data, str):
                        enum_val = type_def["EnumMembers"].get(data, 0)
                self.writer.write_int(enum_val)
                self.layout_writer.log(f"enum({name})", field_name, enum_val)
            else: # 是一个类
                field_sequence = type_def.get("FieldSequence", [])
                
                # 检查是否为包装类 (只有一个集合字段)
                is_wrapper = (len(field_sequence) == 1 and 
                              parse_type_string(field_sequence[0]["Type"])[0] is not None)

                field_values = []
                if isinstance(data, str) and delimiters:
                    # 如果是包装类，字符串数据属于其内部字段，此处不分割
                    if is_wrapper:
                        field_values = [data]
                    else:
                        delimiter = delimiters.popleft()
                        field_values = data.split(delimiter)
                elif isinstance(data, list):
                    field_values = data

                self.layout_writer.enter_scope(f"{field_name}: {name}")
                for i, field_def in enumerate(field_sequence):
                    f_name = field_def["Field"]
                    f_type_syntax = field_def["Type"]
                    f_value = field_values[i] if i < len(field_values) else None
                    self._write_recursive(f_value, f_type_syntax, f_name, delimiters.copy())
                self.layout_writer.exit_scope()

class BinaryDataWriter:
    """
    接收 ConfigTable 对象，并协调将其序列化为二进制数据和布局文本的过程。
    """
    def __init__(self, type_system):
        self.type_system = type_system

    def write(self, table: ConfigTable) -> tuple[bytes, str]:
        """
        将单个 ConfigTable 序列化。
        
        Args:
            table: 待序列化的 ConfigTable 对象。
        
        Returns:
            一个元组 (二进制数据, 布局文本)。
        """
        writer = BinaryWriter()
        layout_writer = LayoutWriter()
        handler = CustomBinaryDataHandler(self.type_system, writer, layout_writer)

        if table.is_flat_table:
            layout_writer.log("Flat Table", table.target_type_name, f"from {table.excel_file_name}")
            layout_writer.enter_scope(f"Properties of {table.target_type_name}")
            for row in table.rows:
                handler.write_value(row.value, row.type_syntax, {'col': row.key})
            layout_writer.exit_scope()
        else:
            layout_writer.log("Standard Table", table.target_type_name, f"{len(table.data_rows)} rows from {table.excel_file_name}")
            writer.write_int(len(table.data_rows))
            layout_writer.enter_scope("Data Rows")
            for i, data_row in enumerate(table.data_rows):
                layout_writer.enter_scope(f"Row [{i}]")
                for j, field_def in enumerate(table.rows):
                    handler.write_value(data_row[j], field_def.type_syntax, {'col': field_def.key})
                layout_writer.exit_scope()
            layout_writer.exit_scope()
            
        return writer.buffer, layout_writer.get_content()
