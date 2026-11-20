import importlib
import pkgutil

for _, module_name, _ in pkgutil.iter_modules([__path__[0] + "/provider"]):
    mod = importlib.import_module(f".provider.{module_name}", __name__)
    for attr in dir(mod):
        if attr.startswith("get_direct_link_from_") or attr.startswith(
            "get_preview_image_link_from_"
        ):
            globals()[attr] = getattr(mod, attr)
