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

# Regex to parse the unified type syntax, e.g., 'list(Item)["~", "#"]'
UNIFIED_TYPE_SYNTAX_REGEX = re.compile(r"^(.*?)(\[.*\])?$")
# Regex to parse collection types like list(Item)
TYPE_STRING_REGEX = re.compile(r"^(list|set|array)\((.*)\)$")

class BinaryWriter:
    """A helper class to write primitive types to a bytearray."""
    def __init__(self):
        self.buffer = bytearray()

    def write_bool(self, v: bool):
        """Writes a boolean value as 1 byte (0 or 1)."""
        self.buffer += struct.pack('?', bool(v))

    def write_int(self, v: int):
        """Writes an integer as 4 bytes, little-endian."""
        self.buffer += struct.pack('<i', int(v) if v is not None else 0)

    def write_long(self, v: int):
        """Writes a long integer as 8 bytes, little-endian."""
        self.buffer += struct.pack('<q', int(v) if v is not None else 0)

    def write_float(self, v: float):
        """Writes a float as 4 bytes."""
        self.buffer += struct.pack('<f', float(v) if v is not None else 0.0)

    def write_string(self, v: str):
        """
        Writes a string by first writing its UTF-8 byte length (as a 4-byte int),
        then writing the actual encoded bytes.
        """
        if v is None:
            self.write_int(0)
            return
        encoded_bytes = str(v).encode('utf-8')
        self.write_int(len(encoded_bytes))
        self.buffer += encoded_bytes

class LayoutWriter:
    """A helper class to write the binary layout structure to a text file for debugging."""
    def __init__(self):
        self.lines = []
        self.indent_level = 0

    def _indent(self) -> str:
        return "  " * self.indent_level

    def log(self, type_name: str, field_name: str, value: any):
        """Records a single line of layout information."""
        value_str = repr(value)
        if len(value_str) > 100:
            value_str = value_str[:100] + "..."
        self.lines.append(f"{self._indent()}[{type_name}] {field_name} = {value_str}\n")

    def enter_scope(self, scope_name: str):
        """Enters a new data scope (like a class or list), increasing indent."""
        self.lines.append(f"{self._indent()}{scope_name} {{\n")
        self.indent_level += 1

    def exit_scope(self):
        """Exits the current data scope, decreasing indent."""
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}}\n")
        
    def get_content(self) -> str:
        """Gets the complete layout text content."""
        return "".join(self.lines)

def parse_type_string(type_str: str):
    """Parses a collection type string like 'list(Item)'."""
    if not isinstance(type_str, str): return None, type_str
    match = TYPE_STRING_REGEX.match(type_str.strip())
    if match: return match.group(1), match.group(2)
    return None, type_str

def parse_unified_syntax(type_syntax_str: str):
    """Parses the unified type syntax, e.g., 'list(Item)["~", "#"]'."""
    if not isinstance(type_syntax_str, str): return type_syntax_str, None
    match = UNIFIED_TYPE_SYNTAX_REGEX.match(type_syntax_str.strip())
    if not match: return type_syntax_str, None
    main_type, delimiters_str = match.group(1).strip(), match.group(2)
    if delimiters_str:
        try: return main_type, json.loads(delimiters_str)
        except json.JSONDecodeError: raise ValueError(f"Invalid delimiter format in type string: {delimiters_str}.")
    return main_type, None

class CustomBinaryDataHandler:
    """
    Parses data from a normalized structure and writes it to a binary stream.
    This class contains the core recursive writing logic.
    """
    def __init__(self, type_system, writer: BinaryWriter, layout_writer: LayoutWriter):
        self.type_system = type_system
        self.writer = writer
        self.layout_writer = layout_writer

    def _normalize_data(self, raw_value, delimiters: deque):
        """Recursively normalizes a string with delimiters into a nested list."""
        if not delimiters: return raw_value
        delimiter = delimiters.popleft()
        if isinstance(raw_value, list):
            return [self._normalize_data(item, delimiters.copy()) for item in raw_value]
        if isinstance(raw_value, str):
            return [self._normalize_data(part, delimiters.copy()) for part in raw_value.split(delimiter)]
        return raw_value

    def write_value(self, raw_value, type_syntax_str: str, context: dict):
        """
        The main entry point for writing a value. It normalizes the data source
        and then calls the recursive writer.
        """
        if raw_value is None or raw_value == '': raw_value = None
        type_str, delimiters = parse_unified_syntax(type_syntax_str)
        
        if delimiters and isinstance(raw_value, str):
            normalized_value = self._normalize_data(raw_value, deque(delimiters))
        elif isinstance(raw_value, str) and raw_value.strip().startswith(('{', '[')):
            try: normalized_value = json.loads(raw_value)
            except json.JSONDecodeError: normalized_value = raw_value
        else: normalized_value = raw_value
        
        self._write_recursive(normalized_value, type_str, context.get('col', 'N/A'))

    def _write_recursive(self, data, type_str: str, field_name: str):
        """Writes normalized data to the binary stream based on its type string."""
        collection_type, inner_type_str = parse_type_string(type_str)
        if collection_type:
            items = data if isinstance(data, list) else []
            self.writer.write_int(len(items))
            self.layout_writer.log("int", f"{field_name}_count", len(items))
            self.layout_writer.enter_scope(f"{field_name}: {type_str}")
            for i, item in enumerate(items):
                self._write_recursive(item, inner_type_str, f"[{i}]")
            self.layout_writer.exit_scope()
            return
            
        name = inner_type_str
        if name == "string": self.writer.write_string(data); self.layout_writer.log("string", field_name, data)
        elif name == "int": self.writer.write_int(data); self.layout_writer.log("int", field_name, data)
        elif name == "long": self.writer.write_long(data); self.layout_writer.log("long", field_name, data)
        elif name == "bool":
            bool_val = str(data).lower() in ['true', '1', 'yes'] if isinstance(data, str) else bool(data)
            self.writer.write_bool(bool_val); self.layout_writer.log("bool", field_name, bool_val)
        elif name == "float": self.writer.write_float(data); self.layout_writer.log("float", field_name, data)
        else:
            type_def = self.type_system.get_type(name)
            if type_def.get("TargetTypeAsEnum"):
                enum_val = 0
                if data is not None:
                    if isinstance(data, int): enum_val = data
                    elif isinstance(data, str): enum_val = type_def["EnumMembers"].get(data, 0)
                self.writer.write_int(enum_val)
                self.layout_writer.log(f"enum({name})", field_name, enum_val)
            else: # It's a class
                self.layout_writer.enter_scope(f"{field_name}: {name}")
                field_values = data if isinstance(data, list) else []
                for i, field_def in enumerate(type_def.get("FieldSequence", [])):
                    f_name = field_def["Field"]
                    f_type_syntax = field_def["Type"]
                    f_value = field_values[i] if i < len(field_values) else None
                    self._write_recursive(f_value, f_type_syntax, f_name)
                self.layout_writer.exit_scope()

class BinaryDataWriter:
    """
    Receives a ConfigTable object and orchestrates the serialization process.
    """
    def __init__(self, type_system):
        self.type_system = type_system

    def write(self, table: ConfigTable) -> tuple[bytes, str]:
        """
        Serializes a ConfigTable object into a byte array and a layout string.
        
        Args:
            table: The ConfigTable object to serialize.
        
        Returns:
            A tuple containing (binary_data, layout_text).
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
