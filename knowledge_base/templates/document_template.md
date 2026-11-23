{#- Układ całego dokumentu - szablon Jinja2, pierwsza wersja do zmiany przez zespół.
    Dostępne zmienne: project_name, formal_part (gotowa część formalna z formal_template.md),
    descriptive_part (rozdziały części opisowej z nagłówkami ###, ułożone przez kod). -#}
# Dokumentacja - {{ project_name }}

{{ formal_part }}
## Część opisowa

{{ descriptive_part }}
