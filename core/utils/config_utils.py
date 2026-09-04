from ruamel.yaml import YAML
import os
import threading

CONFIG_PATH = 'config.yaml'
API_KEY_ENV = "VIDEOLINGO_API_KEY"
API_KEY_REGISTRY_PATH = r"Environment"
lock = threading.Lock()

yaml = YAML()
yaml.preserve_quotes = True


def _registry_api_key():
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, API_KEY_REGISTRY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, API_KEY_ENV)
        return str(value).strip()
    except OSError:
        return ""


def _external_api_key():
    return os.environ.get(API_KEY_ENV, "").strip() or _registry_api_key()


def _write_user_api_key(value):
    value = str(value).strip()
    os.environ[API_KEY_ENV] = value
    if os.name == "nt":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, API_KEY_REGISTRY_PATH) as key:
            winreg.SetValueEx(key, API_KEY_ENV, 0, winreg.REG_SZ, value)


def migrate_api_key_from_config():
    """Move a legacy YAML key into the current user's environment once."""
    with lock:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
            data = yaml.load(file)
        legacy = str((data.get("api") or {}).get("key") or "").strip()
        if not legacy or legacy.lower().startswith(("your_", "replace_")):
            return False
        if not _external_api_key():
            _write_user_api_key(legacy)
        data["api"]["key"] = ""
        with open(CONFIG_PATH, 'w', encoding='utf-8') as file:
            yaml.dump(data, file)
    return True

# -----------------------
# load & update config
# -----------------------

def load_key(key):
    if key == "api.key":
        external = _external_api_key()
        if external:
            return external
    with lock:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
            data = yaml.load(file)

    keys = key.split('.')
    value = data
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            raise KeyError(f"Key '{k}' not found in configuration")
    return value

def update_key(key, new_value):
    with lock:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
            data = yaml.load(file)

        keys = key.split('.')
        current = data
        for k in keys[:-1]:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return False

        if isinstance(current, dict) and keys[-1] in current:
            current[keys[-1]] = new_value
            with open(CONFIG_PATH, 'w', encoding='utf-8') as file:
                yaml.dump(data, file)
            return True
        else:
            raise KeyError(f"Key '{keys[-1]}' not found in configuration")
        
# basic utils
def get_joiner(language):
    if language in load_key('language_split_with_space'):
        return " "
    elif language in load_key('language_split_without_space'):
        return ""
    else:
        raise ValueError(f"Unsupported language code: {language}")

if __name__ == "__main__":
    print(load_key('language_split_with_space'))
