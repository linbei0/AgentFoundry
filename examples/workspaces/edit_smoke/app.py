"""
app.py - edit smoke 示例模块

提供一个故意写错的 add 函数，供真实 LLM smoke 修复。
"""


def add(a, b):
    return a - b
