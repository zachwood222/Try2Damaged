from jinja2 import Environment, FileSystemLoader, select_autoescape

def get_env(template_dir: str):
    return Environment(loader=FileSystemLoader(template_dir), autoescape=select_autoescape(['html','xml']))

def render_template(template_dir: str, name: str, context: dict) -> str:
    env = get_env(template_dir)
    tpl = env.get_template(name)
    return tpl.render(**context)
