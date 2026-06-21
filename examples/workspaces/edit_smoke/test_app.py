"""
test_app.py - edit smoke 验证测试

验证 add 函数修复后能正确返回两数之和。
"""

from app import add


def test_add_returns_sum():
    assert add(2, 3) == 5
