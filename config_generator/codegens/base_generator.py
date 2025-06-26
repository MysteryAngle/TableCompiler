# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /config_generator/codegens/base_generator.py
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

# 为了避免循环导入，并让类型提示工具正常工作
if TYPE_CHECKING:
    from ..models import ConfigTable
    from ..readers import TypeSystem

class BaseCodeGenerator(ABC):
    """
    所有语言代码生成器的抽象基类。
    
    这个类定义了一个标准的接口，任何新的语言生成器都必须实现它。
    这确保了主执行脚本 (`run.py`) 可以用同样的方式调用任何语言的生成器。
    """
    def __init__(self, type_system: 'TypeSystem', temp_dir: str, target_config: dict):
        """
        初始化生成器基类。

        Args:
            type_system: 已加载所有类型定义的 TypeSystem 实例。
            temp_dir: 用于存放生成文件的临时目录路径。
            target_config: 在 config.toml 中为当前目标语言定义的配置对象。
        """
        self.type_system = type_system
        self.temp_dir = temp_dir
        self.target_config = target_config
        self.generated_files = set() # 用于防止重复生成同一个文件

    @abstractmethod
    def generate_all(self, tables: list['ConfigTable']):
        """
        为所有配置表生成代码的主入口方法。
        
        子类必须实现这个方法，以定义针对特定语言的完整代码生成流程。

        Args:
            tables: 一个包含所有待处理配置表 (ConfigTable) 的列表。
        """
        pass
