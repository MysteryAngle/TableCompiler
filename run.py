# ==============================================================================
# TableCompiler
# Copyright (c) 2025, Alex Liao. All rights reserved.
#
# This file is part of the TableCompiler project, a tool designed to
# compile Excel configuration sheets into type-safe code and binary data
# for high-performance projects.
# ==============================================================================

# /run.py
import click
import tomli
import os
import shutil
import importlib
from config_generator.readers import ConfigReader
from config_generator.writers import BinaryDataWriter
from config_generator.codegens.base_generator import BaseCodeGenerator
from config_generator.wizard import typedef_command

# --- 全局配置加载 ---
try:
    with open("config.toml", "rb") as f:
        cfg = tomli.load(f)
except FileNotFoundError:
    click.echo(click.style("错误: 未找到 'config.toml' 配置文件。", fg='red'), err=True)
    exit(1)

# --- 提取配置常量 ---
INPUT_DIR = cfg['paths']['input_dir']
METADATA_DIR = cfg['paths']['metadata_dir']
OUTPUT_DIR = cfg['paths']['output_dir']
TEMP_DIR = cfg['paths']['temp_dir']
DATA_LAYOUT_DIR = cfg['paths']['data_layout_dir']
BINARY_COPY_DEST = cfg['paths']['binary_copy_destination']
TYPE_DEF_SUFFIX = cfg['file_suffixes']['type_def']
INNER_TYPE_DEF_SUFFIX = cfg['file_suffixes']['inner_type_def']
BINARY_EXTENSION = cfg['file_suffixes'].get('binary_extension', '.dat')


def get_generator_class(language: str) -> type[BaseCodeGenerator]:
    """动态导入并获取指定语言的生成器类。"""
    try:
        module = importlib.import_module(f"config_generator.codegens.{language}.generator")
        return getattr(module, "CodeGenerator")
    except (ImportError, AttributeError) as e:
        raise ImportError(f"无法为语言 '{language}'找到有效的生成器: {e}")

@click.group(context_settings=dict(help_option_names=['-h', '--help']))
@click.pass_context
def cli(ctx):
    """配置表生成器 CLI"""
    ctx.obj = {
        'INPUT_DIR': INPUT_DIR, 'METADATA_DIR': METADATA_DIR,
        'TYPE_DEF_SUFFIX': TYPE_DEF_SUFFIX, 'INNER_TYPE_DEF_SUFFIX': INNER_TYPE_DEF_SUFFIX
    }

@cli.command()
@click.option('--force', '-f', is_flag=True, help="强制重新生成所有配置，不进行询问。")
@click.option('--debug', is_flag=True, help="启用调试模式，在出错时打印详细信息。")
def generate(force, debug):
    """从Excel文件生成二进制数据和所有已启用的目标语言代码。"""
    click.echo(click.style("===== 运行生成器 =====", bold=True))
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

    try:
        reader = ConfigReader(INPUT_DIR, METADATA_DIR, TYPE_DEF_SUFFIX)
        all_tables = reader.read_all()

        # 1. 生成二进制数据和布局文件
        click.echo("\n>>> 正在生成二进制数据和布局文件...")
        binary_writer = BinaryDataWriter(reader.type_system)
        
        temp_data_dir = os.path.join(TEMP_DIR, "data")
        temp_layout_dir = os.path.join(TEMP_DIR, DATA_LAYOUT_DIR)
        os.makedirs(temp_data_dir, exist_ok=True)
        os.makedirs(temp_layout_dir, exist_ok=True)
        
        for table in all_tables:
            binary_data, layout_text = binary_writer.write(table)
            
            # 写入二进制文件
            dat_filepath = os.path.join(temp_data_dir, f"{table.base_name}{BINARY_EXTENSION}")
            with open(dat_filepath, 'wb') as f: f.write(binary_data)
            click.echo(f"    - 已生成: {os.path.relpath(dat_filepath)}")

            # 写入布局文件
            layout_filepath = os.path.join(temp_layout_dir, f"{table.base_name}_layout.txt")
            with open(layout_filepath, 'w', encoding='utf-8') as f: f.write(layout_text)
            click.echo(f"    - 已生成: {os.path.relpath(layout_filepath)}")

        # 2. 生成各语言代码
        for target in cfg.get("targets", []):
            if not target.get("enabled"): continue
            lang = target['language']
            click.echo(f"\n>>> 正在为语言 '{lang}' 生成代码...")
            GeneratorClass = get_generator_class(lang)
            generator = GeneratorClass(reader.type_system, TEMP_DIR, target)
            generator.generate_all(all_tables)

        # 3. 将所有临时文件移动到最终输出目录
        click.echo(click.style("\n>>> 所有文件处理成功。", fg='green', bold=True))
        shutil.copytree(TEMP_DIR, OUTPUT_DIR, dirs_exist_ok=True)
        
        # 4. 如果配置了复制目标路径，则执行复制操作
        if BINARY_COPY_DEST:
            click.echo(f"\n>>> 正在将二进制文件复制到: {BINARY_COPY_DEST}...")
            final_data_dir = os.path.join(OUTPUT_DIR, "data")
            if os.path.exists(final_data_dir):
                os.makedirs(BINARY_COPY_DEST, exist_ok=True)
                shutil.copytree(final_data_dir, BINARY_COPY_DEST, dirs_exist_ok=True)
                click.echo(click.style("    - 复制成功。", fg='green'))
            else:
                click.echo(click.style("    - 警告: 未找到 'output/data' 目录，跳过复制。", fg='yellow'))

        click.echo(click.style("===== 生成完毕! =====", bold=True))

    except Exception as e:
        if debug:
            import traceback
            traceback.print_exc()
        else:
            click.echo(click.style("提示: 使用 --debug 参数运行以获取更详细的错误信息。", fg='yellow'))
        click.echo(click.style(f"\n致命错误: {e}", fg='red', bold=True), err=True)
    finally:
        if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
        click.echo("临时目录已清理。")

cli.add_command(generate)
cli.add_command(typedef_command)

if __name__ == '__main__':
    cli()
