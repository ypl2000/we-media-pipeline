#!/usr/bin/env python3
"""
Shared configuration loader for We-media-pipeline.

This module provides a centralized configuration loading mechanism that:
1. Supports standalone skill usage (skills can work independently)
2. Respects project-level config when running within the pipeline
3. Falls back to environment variables and skill-local configs

Priority order:
  1. Environment variables
  2. Project config (project_root/config.json)
  3. Skill-local config (skill_dir/config.json)
  4. Default values
"""

import os
import sys
import json
from pathlib import Path


def get_platform():
    """Get current platform: 'windows', 'linux', or 'darwin' (macOS)."""
    if sys.platform.startswith('win'):
        return 'windows'
    elif sys.platform.startswith('linux'):
        return 'linux'
    elif sys.platform == 'darwin':
        return 'darwin'
    return 'unknown'


def _windows_desktop_dir():
    """Windows 上问注册表要真实桌面路径（桌面可能被重定向到别的盘）。"""
    try:
        import winreg
        key = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            path, _ = winreg.QueryValueEx(k, 'Desktop')
        # 注册表里是 %USERPROFILE%\Desktop 之类的环境变量
        return Path(os.path.expandvars(path))
    except Exception:
        return None


def get_desktop_dir():
    """
    Get the desktop directory for the current platform.

    Windows: 真实桌面路径（读注册表，支持重定向到其他盘）
    macOS: ~/Desktop
    Linux: ~/Desktop (or ~/桌面 on some distros)
    """
    home = Path.home()

    if get_platform() == 'windows':
        desktop = _windows_desktop_dir()
        if desktop is None or not desktop.exists():
            desktop = home / 'Desktop'
            if not desktop.exists():
                desktop = home / '桌面'
    elif get_platform() == 'darwin':
        desktop = home / 'Desktop'
    else:
        desktop = home / 'Desktop'
        if not desktop.exists():
            desktop = home / '桌面'
        if not desktop.exists():
            desktop = home

    return str(desktop.resolve())


def get_default_output_dir():
    """Get default output directory from project config, or auto-detect desktop."""
    output_dir = get_config_value('default_output_dir')
    if output_dir and str(output_dir).strip():
        return output_dir
    
    return os.path.join(get_desktop_dir(), '自媒体输出')


def get_output_dir(*parts):
    """产物输出目录 = 输出根目录 / parts...，并确保不落在代码仓库里。

    输出根目录由 config.json 的 default_output_dir 决定（默认在桌面）。
    守卫：结果若落在项目目录内，直接报错——产物不该写进仓库。

    Args:
        *parts: 相对输出根目录的子路径，如 ('baidu_images',)

    Returns:
        str: 绝对路径
    """
    root = Path(get_default_output_dir()).resolve()
    target = root.joinpath(*parts) if parts else root
    target = target.resolve()

    project = get_project_root()
    if target == project or project in target.parents:
        raise ValueError(
            f'产物目录不能位于代码仓库内: {target}\n'
            f'请改 config.json 的 default_output_dir（当前: {get_default_output_dir()}）'
        )
    return str(target)


def get_project_root():
    """Get the project root directory (where config.json is located)."""
    return Path(__file__).parent.parent.resolve()


def get_skill_dir(skill_name=None):
    """Get the skill directory. If skill_name is None, returns this file's parent directory."""
    if skill_name is None:
        return Path(__file__).parent.parent.resolve()
    return get_project_root() / skill_name


def load_project_config():
    """Load configuration from project root config.json."""
    config_path = get_project_root() / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_skill_config(skill_name):
    """Load configuration from skill-local config.json."""
    skill_dir = get_skill_dir(skill_name)
    config_path = skill_dir / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_config_value(key, default=None, skill_name=None):
    """
    Get a configuration value by key with fallback chain.

    Priority:
      1. Environment variable (uppercase key with underscores)
      2. Project config
      3. Skill-local config
      4. Default value

    Args:
        key: Configuration key (supports dot notation for nested values, e.g., 'news_search.default_days')
        default: Default value if key not found
        skill_name: If provided, also checks skill-local config

    Returns:
        The configuration value or default
    """
    keys = key.split('.')

    env_key = key.upper().replace('.', '_')
    env_value = os.environ.get(env_key)
    if env_value is not None:
        return env_value

    project_config = load_project_config()
    value = project_config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            value = None
            break

    if value is not None:
        return value

    if skill_name:
        skill_config = load_skill_config(skill_name)
        value = skill_config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                value = None
                break
        if value is not None:
            return value
    
    return default


def get_tavily_api_key():
    """Get Tavily API key with priority: env var > project config > skill config."""
    key = get_config_value('tavily_api_key', skill_name='news-searcher')
    if key:
        return key
    return os.environ.get('TAVILY_API_KEY')


def get_minimax_api_key():
    """Get MiniMax API key with priority: env var > project config."""
    return get_config_value('minimax_api_key') or os.environ.get('MINIMAX_API_KEY')


def get_news_default_days():
    """Get default days for news search."""
    return get_config_value('news_search.default_days', 7, skill_name='news-searcher')


def get_news_default_results():
    """Get default results count for news search."""
    return get_config_value('news_search.default_results', 10, skill_name='news-searcher')


def get_image_default_results():
    """Get default results count for image search."""
    return get_config_value('image_search.default_results', 6, skill_name='image-searcher')


def get_image_min_width():
    """Get minimum image width for filtering."""
    return get_config_value('image_search.min_width', 800, skill_name='image-searcher')


def get_image_min_height():
    """Get minimum image height for filtering."""
    return get_config_value('image_search.min_height', 600, skill_name='image-searcher')


def get_image_search_engine():
    """Get preferred image search engine ('baidu')."""
    return get_config_value('image_search.search_engine', 'baidu', skill_name='image-searcher')


# ============== 图表生成配置 ==============
# 图表功能已随 step3_generate_charts.py 一起移除（见 77effaf），
# 相关的配置项和 getter 一并删掉，避免留下没人读的死配置。


def check_required_apis():
    """Check which API keys are configured."""
    return {
        'tavily': bool(get_tavily_api_key()),
        'minimax': bool(get_minimax_api_key()),
    }


def print_config_status():
    """Print current configuration status."""
    status = check_required_apis()
    project_root = get_project_root()
    
    print("=" * 60)
    print("We-media-pipeline Configuration Status")
    print("=" * 60)
    print(f"Project root: {project_root}")
    print(f"Config file: {project_root / 'config.json'}")
    print()
    
    print("API Keys:")
    for api, configured in status.items():
        icon = "✓" if configured else "✗"
        name = api.capitalize()
        print(f"  {icon} {name}: {'Configured' if configured else 'Not configured'}")
    
    print()
    print("Default Settings:")
    print(f"  News days: {get_news_default_days()}")
    print(f"  News results: {get_news_default_results()}")
    print(f"  Image results: {get_image_default_results()}")
    print(f"  Image min size: {get_image_min_width()}x{get_image_min_height()}")
    print(f"  Image search engine: {get_image_search_engine()}")
    print(f"  Output dir: {get_default_output_dir()}")
    
    print()
    print("=" * 60)


if __name__ == '__main__':
    # CLI: --get <key> 打印单个配置值（供 workflow 等外部调用方读取）
    if len(sys.argv) > 2 and sys.argv[1] == '--get':
        key = sys.argv[2]
        if key == 'default_output_dir':
            print(get_default_output_dir())
        else:
            print(get_config_value(key, ''))
    else:
        print_config_status()