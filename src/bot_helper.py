import random


def get_welcome_phrase(user_name: str) -> str:
    """Возвращает рандомное приветственное сообщение"""
    phrases = [
        f"Привет, {user_name}!",
        f"С возвращением, {user_name}!",
        f"И снова привет, {user_name}!",
        f"Рад видеть, {user_name}!",
    ]

    return random.choice(phrases)