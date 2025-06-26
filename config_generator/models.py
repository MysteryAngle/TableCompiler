# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/models.py
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ConfigRow:
    """
    表示平铺表中的一行，或标准表中的一个字段定义。
    它封装了配置项的元信息。
    """
    key: str          # 字段名或属性名
    type_syntax: str  # 完整的类型语法，如 'list(Item)["~"]'
    value: Any = None   # 仅平铺表使用，存放该属性的值
    comment: str = "" # 字段的注释

@dataclass
class ConfigTable:
    """
    一个语言无关的、表示单个Excel配置表所有信息的中间数据结构。
    读取模块的最终输出，也是写入模块和代码生成模块的输入。
    """
    excel_file_name: str
    base_name: str
    is_flat_table: bool
    target_type_name: str               # 主类名或单例类名
    table_comment: str = ""             # 用于存储整个表格的注释
    primary_key_fields: list[str] = field(default_factory=list) # 仅标准表使用
    rows: list[ConfigRow] = field(default_factory=list)         # 存放字段定义 (标准表) 或属性定义 (平铺表)
    data_rows: list[list[Any]] = field(default_factory=list)    # 存放纯数据行 (仅标准表)
