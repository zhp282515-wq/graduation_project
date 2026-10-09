def fmt_duration(seconds: float) -> str:
    """把秒数格式化为人类可读时长:60s 内按秒,超则进位到分/时/天。"""
    if seconds < 60:
        return f"{seconds:.2f}秒"
    if seconds < 3600:
        return f"{seconds / 60:.2f}分钟"
    if seconds < 86400:
        return f"{seconds / 3600:.2f}小时"
    return f"{seconds / 86400:.2f}天"


if __name__ == '__main__':
    print(fmt_duration(37.1))
    print(fmt_duration(90))
    print(fmt_duration(7200))
    print(fmt_duration(200000))