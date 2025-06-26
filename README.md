# TableCompiler 使用文档

## 1. 简介

欢迎使用 TableCompiler！

这是一个专为高性能项目设计的、可扩展的命令行工具，旨在将 Excel 配置表自动化地编译为项目中可直接使用的、类型安全的代码和高效的自定义二进制数据，并支持 C#, ~~TypeScript, Java, Go, JavaScript~~（待完善） 等多种目标语言。

### 核心特性

* **多语言支持**: 通过可插拔的架构，可以轻松地为多种语言生成配置代码。
* **零运行时依赖**: 生成的代码是原生的，无需任何第三方库。
* **极致性能**: 通过生成与数据结构完全匹配的自定义二进制读写逻辑，实现极高的加载速度。
* **类型安全**: 所有配置都在生成阶段进行严格的类型校验。
* **统一的类型语法**: 使用统一、直观的 `list(Item)["~", "#"]` 语法来定义类型和解析规则。
* **两种表格模式**: 支持传统的“标准表格”（一行一数据）和灵活的“平铺式表格”（一行一属性）。
* **交互式向导**: 内置的 `typedef` 命令行向导可以引导您创建和维护类型定义文件。

## 2. 项目结构

一个标准的 TableCompiler 项目应遵循以下目录结构：

```
TableCompiler/
├── configs/                  # 存放 Excel源文件
│   ├── Levels.xlsx
│   └── Global.xlsx
├── metadata/                 # 存放所有类型定义文件
│   ├── Levels.typedef.json
│   ├── Global.typedef.json
│   └── InnerTypes/
│       └── Item.innertypesdef.json
├── output/                   # 所有生成文件的根目录
│   ├── csharp/
│   ├── data/
│   ├── go/
│   ├── java/
│   ├── javascript/
│   └── typescript/
├── config_generator/         # 生成器核心模块
│   ├── __init__.py
│   ├── models.py
│   ├── readers.py
│   ├── writers.py
│   ├── wizard.py
│   └── codegens/
│       ├── __init__.py
│       ├── base_generator.py
│       ├── csharp/
│       │   ├── generator.py
│       │   └── templates/
│       ├── go/
│       ├── java/
│       ├── javascript/
│       └── typescript/
├── config.toml               # 全局配置文件
└── run.py                    # 主执行入口
```

## 3. 快速上手

### 3.1. 安装

1.  **安装 Python**: 请确保您的系统已安装 Python 3.8 或更高版本。
2.  **安装 uv**: `uv` 是一个极速的 Python 包安装器。
    ```bash
    # macOS / Linux
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Windows (PowerShell)
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
3.  **创建虚拟环境并安装依赖**: 在项目根目录下打开终端，运行：
    ```bash
    # 创建并激活虚拟环境
    uv venv
    source venv/bin/activate # macOS/Linux 或 .\venv\Scripts\activate on Windows
    
    # 安装所有必要的库
    uv pip install click openpyxl jinja2 tomli inflection
    ```

### 3.2. 运行

* **生成代码和数据**:
    ```bash
    python run.py generate
    ```
* **启动类型定义向导**:
    ```bash
    python run.py typedef
    ```

## 4. 核心概念：关注点分离

TableCompiler 的设计核心是**关注点分离**，将“数据结构定义”与“数据源解析”清晰地解耦。

### 4.1. 定义数据结构 (`.innertypesdef.json`)

`.innertypesdef.json` 文件用于定义可在项目中**复用**的数据结构“蓝图”，如 `Item`, `Reward` 等。

* **它的唯一职责是**: **定义一个数据类型的内部结构**。
* 它只关心这个类型有哪些字段 (`FieldSequence`)、以及每个字段是什么类型。
* 它非常纯粹，完全不知道这些数据将从 Excel 的哪个单元格、以何种格式被读取。

**示例：创建一个物品蓝图 `metadata/InnerTypes/Item.innertypesdef.json`**
```json
{
    "TypeDefines": {
        "Item": {
            "TargetType": "Common/Item",
            "Comment": "Represents an item with an ID and a count.",
            "FieldSequence": [
                {
                    "Field": "ItemId",
                    "Type": "int",
                    "Comment": "The unique ID of the item."
                },
                {
                    "Field": "Count",
                    "Type": "int",
                    "Comment": "The quantity of the item."
                }
            ]
        }
    }
}
```
* `"Item"`: 我们为这个“蓝图”起的唯一名字。
* `TargetType`: 指定生成的类文件存放的相对路径和名称。

### 4.2. 定义如何读取 Excel (统一类型语法)

解析规则通过一种统一的类型语法来定义，其结构为 **`TypeName[Delimiters]`**。

* **`TypeName` (必需)**: 定义数据的类型，如 `int`, `Item`, `list(Item)`。
* **`[Delimiters]` (可选)**: 一个 JSON 数组格式的字符串，定义了从字符串解析数据时，从外到内每一层级所使用的分隔符。**如果省略，则表示数据源为 JSON 数组格式。**

此语法可用于：
1.  **标准表格**的 `.typedef.json` 文件中的 `Type` 字段。
2.  **平铺式表格**的 Excel `Type` 列中。

**语法示例**:
* `list(int)` (从 `[1,2,3]` 这样的 JSON 数组解析)
* `list(Item)["~", "#"]` (从 `'1001#10~1002#5'` 这样的字符串解析)
* `list(list(int))["|", ","]` (从 `'1,2|3,4'` 这样的字符串解析)

## 5. 表格模式

### 5.1. 标准表格

每一行代表一条完整的数据记录。由 `.typedef.json` 文件来描述其结构。

**`Levels.xlsx` 的 `Rewards` 列**: `1003#10~2001#1`
**`metadata/Levels.typedef.json`**:
```json
{
    "ExcelFileName": "Levels.xlsx",
    "TargetType": "Level",
    "Comment": "Defines the configuration for each level in the game.",
    "IsFlatTable": false,
    "ImportTypes": [ "InnerTypes/Item" ],
    "PrimaryKeyFields": ["Id"],
    "FieldSequence": [
        {
            "Field": "Id",
            "Type": "int",
            "Comment": "The unique ID of the level."
        },
        {
            "Field": "Rewards",
            "Type": "list(Item)[\"~\",\"#\"]",
            "Comment": "Rewards for completing the level."
        }
    ]
}
```

### 5.2. 平铺式表格

每一行定义一个独立的配置项，非常适合全局配置。

**`Global.xlsx`**:
| Key | Type | Value | Comment |
|:---|:---|:---|:---|
| DefaultItems | `list(Item)` | `[[1001,10]]` | 默认道具 (JSON) |
| SpecialRewards | `list(Item)["~","#"]`| `2001#1~2002#5`| 特殊奖励 (字符串) |

**`metadata/Global.typedef.json`**:
```json
{
    "ExcelFileName": "Global.xlsx",
    "TargetType": "Global",
    "Comment": "Stores global configuration variables for the game.",
    "IsFlatTable": true,
    "ImportTypes": [ "InnerTypes/Item" ]
}
```
* **生成结果**: 会为 `Global.xlsx` 生成一个单例类，如 `Global.cs`, `Global.ts`。

## 6. 配置文件 `config.toml`

通过 `config.toml` 文件来配置要生成的目标语言。

```toml
[paths]
input_dir = "configs"
metadata_dir = "metadata"
output_dir = "output"
# ...

# 定义所有要生成代码的目标
[[targets]]
language = "csharp"
enabled = true
output_dir = "csharp"
namespace = "Game.Config"
templates_dir = "config_generator/codegens/csharp/templates"

[[targets]]
language = "typescript"
enabled = true
# ...
```

## 7. 命令行用法

### 7.1. 生成代码和数据
```bash
python run.py generate
```
* 该命令会读取 `config.toml`，并为其中所有 `enabled = true` 的目标语言生成代码。
* **`--force` / `-f`**: 跳过检查，强制重新生成。

### 7.2. Typedef 创建与管理向导
```bash
python run.py typedef
```
此向导会引导您完成 `typedef` 文件的创建和维护：
1.  **选择 Excel 文件**和**表格类型**（标准或平铺）。
2.  为标准表格**同步字段**，或为新文件**创建定义**。
3.  **定义字段类型**时，可选择基础、集合或已有的自定义类型，也可以直接**创建新的内部类型**。
4.  当定义一个集合类型时，向导会询问数据源是 JSON 还是分隔符字符串，并相应地引导您**输入所有层级的分隔符**，自动生成正确的类型字符串。

## 8. 扩展：添加新语言支持

1.  **创建插件目录**: 在 `config_generator/codegens/` 下创建新语言的目录，如 `rust/`。
2.  **创建模板**: 在 `rust/templates/` 下放入该语言的 Jinja2 模板。
3.  **实现生成器**: 在 `rust/generator.py` 中，实现一个继承自 `BaseCodeGenerator` 的 `CodeGenerator` 类。
4.  **更新配置**: 在 `config.toml` 中添加一个新的 `[[targets]]` 配置块。
5.  **重新运行**: 执行 `python run.py generate` 即可。
