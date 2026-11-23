Wypełnij pola części formalnej dokumentacji projektu „{{ project_name }}”.

<pola_do_wypelnienia>
{{ fields }}
</pola_do_wypelnienia>

<podsumowanie_projektu>
{{ plan_summary }}
</podsumowanie_projektu>

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
