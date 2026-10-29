"""Server-owned chat model catalogue and shared database selection."""
import json
import os
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'chat_models.json'
KEY_ENV = {'deepseek': 'DEEPSEEK_API_KEY', 'dashscope': 'DASHSCOPE_API_KEY', 'openai': 'OPENAI_API_KEY'}
DEFAULT_SELECTION = {'provider': 'deepseek', 'model': 'deepseek-flash'}


class ModelSettingsError(ValueError):
    """The selected model cannot be used until configuration is repaired."""


def catalogue():
    """Load and validate the deployer's catalogue without ever exposing API keys."""
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        providers = data['providers']
        if not isinstance(providers, list):
            raise ValueError('providers must be a list')
        seen = set()
        result = []
        for provider in providers:
            ident, label, models = provider['id'], provider['label'], provider['models']
            if ident not in KEY_ENV or ident in seen or not isinstance(label, str) or not label.strip() or not isinstance(models, list):
                raise ValueError('invalid provider')
            seen.add(ident)
            choices, model_ids = [], set()
            for model in models:
                model_id, model_label = model['id'], model['label']
                if not isinstance(model_id, str) or not model_id.strip() or model_id in model_ids or not isinstance(model_label, str) or not model_label.strip():
                    raise ValueError('invalid model')
                if type(model['images']) is not bool or type(model['reasoning']) is not bool:
                    raise ValueError('invalid capabilities')
                model_ids.add(model_id)
                choices.append({'id': model_id, 'label': model_label, 'images': model['images'], 'reasoning': model['reasoning']})
            result.append({'id': ident, 'label': label, 'configured': bool(os.getenv(KEY_ENV[ident], '').strip()), 'models': choices})
        return result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ModelSettingsError('模型配置目录无效，请检查服务端 config/chat_models.json') from exc


def validate_selection(selection, providers=None):
    providers = catalogue() if providers is None else providers
    provider = next((item for item in providers if item['id'] == selection['provider']), None)
    if provider is None:
        raise ModelSettingsError('当前供应商已不在服务端模型目录中，请管理员重新配置')
    model = next((item for item in provider['models'] if item['id'] == selection['model']), None)
    if model is None:
        raise ModelSettingsError('当前模型已不在服务端模型目录中，请管理员重新配置')
    if not provider['configured']:
        raise ModelSettingsError(f"{provider['label']} 的 API Key 未配置，请管理员检查服务端环境变量")
    return {'provider': provider['id'], 'model': model['id'], 'images': model['images'], 'reasoning': model['reasoning']}


class ModelSettingsRepository:
    def __init__(self, conn):
        self.conn = conn

    def setup(self):
        self.conn.execute('''CREATE TABLE IF NOT EXISTS chat_model_settings (
            singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
            provider TEXT NOT NULL, model TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )''')

    def get(self):
        row = self.conn.execute('SELECT provider, model FROM chat_model_settings WHERE singleton=true').fetchone()
        return {'provider': row['provider'], 'model': row['model']} if row else DEFAULT_SELECTION.copy()

    def set(self, provider, model):
        self.conn.execute('''INSERT INTO chat_model_settings(singleton,provider,model) VALUES (true,%s,%s)
            ON CONFLICT(singleton) DO UPDATE SET provider=EXCLUDED.provider, model=EXCLUDED.model, updated_at=now()''', (provider, model))


def resolve_model_selection(conn):
    return validate_selection(ModelSettingsRepository(conn).get())


def settings_response(conn):
    current = ModelSettingsRepository(conn).get()
    providers = catalogue()
    try:
        validate_selection(current, providers)
        error = None
    except ModelSettingsError as exc:
        error = str(exc)
    return {'current': current, 'providers': providers, 'current_error': error}
