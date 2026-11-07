"""Summarize actual saved model calls without exporting secrets or transcripts."""
from pathlib import Path
import sys,json,statistics
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cqa.store import Store

ROOT=Path(__file__).resolve().parents[1]
store=Store(ROOT/'data/cqa.sqlite')
reference={r['conversation_id']:r for r in json.loads((ROOT/'research/reference_draft.json').read_text(encoding='utf8'))['records']}
calls=[e for e in store.export()['evaluations'] if e['meta']['provider']!='rules']
latest={e['conversation_id']:e for e in calls}
rows=[];eligible=matches=all_matches=all_labels=0;disagreements=[]
for cid,e in latest.items():
    if cid not in reference:continue
    ref=reference[cid];refs={a['criterion_id']:a for a in ref['criteria']};values=[]
    for a in e['original_answers']:
        b=refs[a['criterion_id']];same=a['value']==b['value'];all_matches+=same;all_labels+=1
        if not b['needs_review']:eligible+=1;matches+=same
        if not same:disagreements.append((cid,a['criterion_id'],b['value'],a['value'],b['needs_review']))
    rows.append((cid,ref['language'],e['original_score']['total'],ref['score']['total'],e['meta']['elapsed_seconds'],e['original_score']['gross_error']))
input_tokens=sum(e['meta']['usage'].get('input_tokens',0) or 0 for e in calls)
output_tokens=sum(e['meta']['usage'].get('output_tokens',0) or 0 for e in calls)
text=['# Фактическая проверка Gemini — первый запуск',
      'Источник: сохранённые реальные ответы модели в локальной SQLite-базе. Заглушки и результаты правил исключены.',
      '**Это проверка работоспособности на небольшой целевой выборке, а не доказательство точности на реальных обращениях или на эталоне жюри.** Предварительная разметка создана ассистентом; независимых человеческих оценщиков — 0. Это не A/B-эксперимент: здесь использовался вариант с обязательными доказательствами.',
      f"Модель: **{calls[0]['meta']['model'] if calls else 'ещё нет вызовов'}**. Реальных вызовов: **{len(calls)}**. Диалогов: **{len(rows)}**. Ответов по критериям: **{all_labels}**.",
      f'Токены по данным провайдера: вход {input_tokens}, выход {output_tokens}. Денежная стоимость не вычислена: цены в настройках не заданы. Число токенов не является подтверждением платного тарифа.',
      f'Время запроса: медиана {statistics.median(e["meta"]["elapsed_seconds"] for e in calls):.2f} с.' if calls else 'Время пока не измерено.',
      f'Совпадение с предварительной разметкой: **{all_matches}/{all_labels}** по всем ответам; **{matches}/{eligible}** после исключения заранее отмеченных спорных критериев. Ни одна из этих дробей не является точностью относительно Ground Truth жюри.',
      '| Диалог | Язык | Модель /100 | Предварительная разметка /100 | Время, с | Грубая ошибка |',
      '|---|---|---:|---:|---:|---|']
for cid,lang,total,ref_total,seconds,gross in rows:text.append(f'| {cid} | {lang} | {total:.2f} | {ref_total:.2f} | {seconds:.2f} | {"Да" if gross else "Нет"} |')
text+=['','## Расхождения','| Диалог | Критерий | Предварительно | Модель | Спорный до вызова? |','|---|---|---|---|---|']
for cid,criterion,expected,actual,review in disagreements:text.append(f'| {cid} | {criterion} | {expected} | {actual} | {"Да" if review else "Нет"} |')
if not disagreements:text.append('| — | — | — | — | Расхождений на этой выборке нет |')
text += ['', '## Что проверено',
         '- Модель принимает диалог и актуальный чек-лист и возвращает ответы по заданным критериям.',
         '- Каждый сохранённый AI-результат прошёл проверку схемы, допустимых ступеней, наличия доказательств и совпадения цитат с исходными сообщениями.',
         '- Проверка существования цитаты не доказывает её смысловую достаточность. Доказательность, проверка фактов о продуктах и спорные трактовки требуют отдельного просмотра.',
         '- Нельзя менять эталонную разметку просто ради совпадения с моделью. Разногласия нужно согласовывать независимо.',
         '', '## Дальнейшая проверка',
         'Согласовать трактовки К5/К6/К7, провести парное A/B-сравнение на зафиксированных заданиях, измерить качество на новой независимой выборке. Для A/B нужен сервер с поддержкой вариантов; benchmark.py проверяет версию перед началом. На следующем запуске ключ вводится заново.']
(ROOT/'docs/VALIDATION.md').write_text('\n\n'.join(text).replace('|\n\n|','|\n|'),encoding='utf8')
print(json.dumps({'calls':len(calls),'dialogs':len(rows),'draft_agreement_all':[all_matches,all_labels],'draft_agreement_nondisputed':[matches,eligible],'differences':disagreements},ensure_ascii=False,indent=2))
