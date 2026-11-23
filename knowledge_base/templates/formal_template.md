{#- Układ części formalnej - szablon Jinja2, pierwsza wersja do zmiany przez zespół.
    Dostępne zmienne: project_name, fields - lista pól w kolejności z formal_template.yaml;
    każde pole ma: name, title, type (text | list) i value (tekst albo lista tekstów; puste = brak danych). -#}
## Część formalna - {{ project_name }}
{% for field in fields %}
### {{ field.title }}

{% if not field.value -%}
_Brak danych._
{%- elif field.type == "list" -%}
- {{ field.value | join("\n- ") }}
{%- else -%}
{{ field.value }}
{%- endif %}
{% endfor %}
