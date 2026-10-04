"""生成登录密码的哈希：python -m web.passwd，把输出那一行粘进 config/.env。"""

import getpass

from web.auth import hash_password

if __name__ == "__main__":
    pw = getpass.getpass("设置控制台密码: ")
    if len(pw) < 8 or pw != getpass.getpass("再输入一次: "):
        raise SystemExit("两次不一致，或少于 8 位")
    print(f"DASH_PASSWORD_HASH={hash_password(pw)}")
