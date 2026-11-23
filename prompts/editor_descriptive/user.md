Napisz część opisową dokumentacji projektu „{{ project_name }}”.

<rozdzialy>
{{ sections }}
</rozdzialy>

<podsumowanie_projektu>
{{ plan_summary }}
</podsumowanie_projektu>

<czesc_formalna>
{{ formal_part }}
</czesc_formalna>

<notatki_analitykow>
{{ notes }}
</notatki_analitykow>

<baza_wiedzy>
{{ kb_files }}
</baza_wiedzy>

{% if review_issues %}
<poprzednia_wersja>
{{ previous_document }}
</poprzednia_wersja>

<uwagi_recenzenta>
{{ review_issues }}
</uwagi_recenzenta>
{% endif %}
