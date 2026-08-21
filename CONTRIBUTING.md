# 🤝 Руководство по вкладу в NaloGO

Спасибо за интерес к проекту NaloGO! Мы приветствуем вклад от сообщества.

## 🚀 Быстрый старт

### Установка для разработки

```bash
# Клонирование репозитория
git clone https://github.com/Rusik636/NaloGO.git
cd NaloGO

# Создание виртуального окружения
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate     # Windows

# Установка зависимостей для разработки
pip install -e ".[dev]"
```

### Запуск тестов

```bash
# Все тесты
pytest tests/ -v

# С покрытием
pytest tests/ -v --cov=nalogo --cov-report=html

# Только линтинг
ruff check .

# Только типизация
mypy nalogo/
```

## 📋 Процесс вклада

### 1. Создание Issue

Перед началом работы создайте issue с описанием:
- Что вы хотите добавить/исправить
- Почему это нужно
- Предлагаемое решение

### 2. Создание ветки

```bash
git checkout -b feature/your-feature-name
# или
git checkout -b fix/your-bug-fix
```

### 3. Разработка

- Следуйте стилю кода (black, ruff)
- Добавляйте типизацию (mypy)
- Пишите тесты для новой функциональности
- Обновляйте документацию

### 4. Коммиты

Используйте понятные сообщения коммитов:

```bash
git commit -m "feat: add new API method for user profile"
git commit -m "fix: resolve authentication token refresh issue"
git commit -m "docs: update README with new examples"
```

### 5. Pull Request

- Создайте PR с описанием изменений
- Убедитесь, что все тесты проходят
- Добавьте скриншоты/примеры если нужно

## 🎯 Стандарты кода

### Python стиль

- **Black** - форматирование кода
- **Ruff** - линтинг
- **MyPy** - типизация
- **Docstrings** - документация функций

### Тестирование

- **Pytest** - фреймворк тестирования
- **Pytest-asyncio** - асинхронные тесты
- **Respx** - мокирование HTTP запросов
- **Coverage** - покрытие тестами (минимум 80%)

### Документация

- **README.md** - основная документация
- **Docstrings** - документация функций
- **Examples** - примеры использования
- **Type hints** - типизация

## 🏗️ Архитектура проекта

```
nalogo/
├── __init__.py          # Основные экспорты
├── client.py            # Главный клиент
├── auth.py              # Аутентификация
├── income.py            # Управление доходами
├── receipt.py           # Работа с чеками
├── payment_type.py      # Способы оплаты
├── tax.py               # Налоговая отчетность
├── user.py              # Профиль пользователя
├── _http.py             # HTTP клиент
├── exceptions.py        # Исключения
└── dto/                 # Модели данных
    ├── __init__.py
    ├── income.py
    ├── receipt.py
    └── ...
```

## 🧪 Тестирование

### Структура тестов

```python
# tests/test_auth_async.py
import pytest
import respx
from nalogo import Client

@pytest.mark.asyncio
async def test_create_new_access_token():
    with respx.mock:
        # Настройка мока
        respx.post("https://lknpd.nalog.ru/api/auth/token").mock(
            return_value=httpx.Response(200, json={"token": "test_token"})
        )

        # Тест
        client = Client()
        token = await client.create_new_access_token("inn", "password")
        assert token == "test_token"
```

### Запуск тестов

```bash
# Все тесты
pytest

# Конкретный файл
pytest tests/test_auth_async.py

# С покрытием
pytest --cov=nalogo --cov-report=term-missing

# Параллельно
pytest -n auto
```

## 📚 Документация

### Обновление README

- Добавляйте примеры кода
- Обновляйте таблицы миграции
- Документируйте новые возможности

### Docstrings

```python
async def create_new_access_token(self, inn: str, password: str) -> str:
    """Создает новый токен доступа по ИНН и паролю.

    Args:
        inn: ИНН пользователя
        password: Пароль пользователя

    Returns:
        Токен доступа

    Raises:
        UnauthorizedException: Неверные учетные данные
        ValidationException: Неверный формат данных
    """
```

## 🚀 Релизы

### Версионирование

Проект следует [Semantic Versioning](https://semver.org/):
- **MAJOR** - несовместимые изменения API
- **MINOR** - новая функциональность (обратно совместимая)
- **PATCH** - исправления багов (обратно совместимые)

### Процесс релиза

1. Обновите версию в `nalogo/__init__.py`
2. Обновите `CHANGELOG.md`
3. Создайте тег: `git tag v1.0.0`
4. Отправьте тег: `git push origin v1.0.0`
5. GitHub Actions автоматически создаст релиз

## 🤝 Сообщество

### Общение

- **Issues** - баги и предложения
- **Discussions** - общие вопросы
- **Pull Requests** - вклад в код

### Код поведения

- Будьте уважительны
- Помогайте новичкам
- Конструктивная критика
- Следуйте стандартам проекта

## 📞 Контакты

- **GitHub Issues**: [Создать issue](https://github.com/Rusik636/NaloGO/issues)
- **Email**: contributors@nalogo.com
- **Discussions**: [GitHub Discussions](https://github.com/Rusik636/NaloGO/discussions)

---

**Спасибо за вклад в развитие NaloGO! 🚀**
