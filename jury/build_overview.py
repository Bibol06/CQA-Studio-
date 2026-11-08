"""Build the five-page jury brief from verified aggregate evidence."""
import json
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing,Rect,String,Line,Polygon

ROOT=Path(__file__).resolve().parents[1]
FONT=Path('C:/Windows/Fonts')
pdfmetrics.registerFont(TTFont('Body',str(FONT/'arial.ttf')))
pdfmetrics.registerFont(TTFont('BodyBold',str(FONT/'arialbd.ttf')))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='BodyBold',italic='Body',boldItalic='BodyBold')
STYLE={
 'title':ParagraphStyle('title',fontName='BodyBold',fontSize=25,leading=30,textColor=colors.black,spaceAfter=13),
 'sub':ParagraphStyle('sub',fontName='Body',fontSize=12,leading=17,textColor=colors.black,spaceAfter=10),
 'h':ParagraphStyle('heading',fontName='BodyBold',fontSize=13,leading=18,textColor=colors.black,spaceBefore=14,spaceAfter=7,keepWithNext=True),
 'p':ParagraphStyle('body',fontName='Body',fontSize=10.5,leading=15.2,textColor=colors.HexColor('#222222'),spaceAfter=8),
 'small':ParagraphStyle('small',fontName='Body',fontSize=9,leading=12.5,textColor=colors.HexColor('#555555'),spaceAfter=7),
 'cell':ParagraphStyle('cell',fontName='Body',fontSize=9.4,leading=13.1,textColor=colors.black),
 'th':ParagraphStyle('th',fontName='BodyBold',fontSize=9.4,leading=13.1,textColor=colors.black)}

def p(text,style='p'):return Paragraph(text,STYLE[style])
def table(rows,widths):
 cells=[[p(escape(str(c)),'th' if i==0 else 'cell') for c in row] for i,row in enumerate(rows)]
 t=Table(cells,colWidths=widths,hAlign='LEFT',repeatRows=1)
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf1ee')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#d9d9d9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
 return t

def architecture():
 d=Drawing(505,155)
 nodes=[(0,95,140,48,['Интерфейс','HTML CSS JavaScript']),
        (181,95,142,48,['Python HTTP API','Очередь и проверки']),
        (365,95,140,48,['SQLite','Оценки и история']),
        (181,8,142,48,['Готовая модель','Оценки и основания'])]
 for x,y,w,h,lines in nodes:
  d.add(Rect(x,y,w,h,fillColor=colors.HexColor('#f5f7f5'),strokeColor=colors.HexColor('#a8b5ac'),strokeWidth=.7))
  for i,line in enumerate(lines):d.add(String(x+w/2,y+h-17-i*15,line,fontName='BodyBold' if i==0 else 'Body',fontSize=9.2,textAnchor='middle'))
 for x1,y1,x2,y2 in [(140,119,181,119),(323,119,365,119),(252,95,252,56)]:
  d.add(Line(x1,y1,x2,y2,strokeColor=colors.HexColor('#337357'),strokeWidth=1.2))
  if y1==y2:d.add(Polygon([x2,y2,x2-6,y2+3,x2-6,y2-3],fillColor=colors.HexColor('#337357'),strokeColor=None))
  else:d.add(Polygon([x2,y2,x2-3,y2+6,x2+3,y2+6],fillColor=colors.HexColor('#337357'),strokeColor=None))
 return d

def footer(c,doc):
 c.saveState();c.setFont('Body',8);c.setFillColor(colors.HexColor('#666666'))
 c.drawString(44,814,'FREEDOM CQA STUDIO  /  FANTASTIC FOUR')
 c.drawString(44,26,'Бибол Жайлыбаев  |  8 ноября 2026  |  версия 0.7.0')
 c.drawRightString(551,26,f'{doc.page} / 5');c.restoreState()

def main():
 summary=json.loads((ROOT/'jury/evidence/project_summary.json').read_text(encoding='utf-8'))
 tests=json.loads((ROOT/'jury/evidence/test_summary.json').read_text(encoding='utf-8'))
 assert summary['submission_ok']==65 and summary['submission_error']==0
 assert tests['python_tests.txt']['tests']==141 and tests['javascript_tests.txt']['tests']==18
 story=[]
 story += [p('Freedom CQA Studio','title'),p('Материалы для технической проверки','sub'),p('<b>Бибол Жайлыбаев</b><br/>Команда Fantastic Four<br/>Data Challenge 2026'),
  p('Freedom CQA Studio помогает проверяющему оценивать качество клиентской поддержки по изменяемым правилам, видеть основания и сохранять решение при пересмотре. Рабочий прототип обрабатывает тексты RU KZ EN и дополнительно анализирует записи звонков.'),
  p('Подтверждённый объём','h'),table([['Показатель','Результат'],['Полные оценки DEV','65 из 65 диалогов'],['Ответы по восьми критериям DEV','520'],['Контроль FBroker','10 из 10 чатов, 80 оценок'],['Звонки с парным распознаванием','5'],['Программные тесты','141 Python и 18 JavaScript']],[290,215]),
  p('Что получает проверяющий','h'),p('Карточку диалога с баллами и репликами-доказательствами. Версионируемый чек-лист с весами, шкалами и N/A. Апелляцию, решение с причиной и сохранённую исходную оценку. Дополнительно доступны резюме, рекомендации, очередь и аналитика.'),
  p('Границы результата','h'),p('65/65 означает покрытие набора, а не точность модели. Независимый человеческий эталон ещё не собран. Контроль FBroker завершён: в PROD 10 записей ok. Swap сохранён без оценки. Исходные разговоры и ключи не входят в публичную поставку.'),
  p('Навигация: jury/README.md — вход в пакет; jury/RUNBOOK.md — запуск; jury/REQUIREMENTS.md — соответствие заданию.','small'),PageBreak()]
 story += [p('Архитектура и данные','title'),p('Простой локальный сервис связывает готовую модель с проверяемым процессом оценки. Базовое приложение требует Python 3.11 или новее, интерфейс работает без внешних CDN.'),architecture(),
  p('Как формируется оценка','h'),p('1. Сервер импортирует диалог с исходными ID, ролями и метками времени.<br/>2. Очередь сохраняет снимок чек-листа и параметров модели.<br/>3. Модель возвращает оценки, основания и дополнительные блоки.<br/>4. Код проверяет допустимые значения и ссылки на источник, рассчитывает балл и сохраняет результат.<br/>5. Проверяющий может оспорить критерий и сохранить новое решение.'),
  p('Расчёт выполняет код','h'),p('Итог равен взвешенной сумме нормализованных оценок, делённой на сумму применимых весов и умноженной на 100. N/A исключается из знаменателя. Числовая ступень делится на максимум шкалы. Грубая ошибка хранится отдельно и не обнуляет итог автоматически. Округление — до двух знаков.'),
  p('Исходные данные и экспериментальные версии','h'),p('Оригинал, читаемая редакция и независимое распознавание сохранены раздельно. Аудиособытия и ASR не пересчитывают официальный балл. В source-turns-v4 модель выбирает номера реплик, а сервер подставляет исходный текст. Наличие цитаты не доказывает правильности смыслового вывода.'),
  p('Готовая модель не обучалась на DEV. SQLite и один обработчик подходят для локального MVP; роли, промышленное хранение и интеграции требуют дальнейшей разработки.','small'),PageBreak()]
 story += [p('Проверка требований','title'),p('Сопоставление с Student Guide v3 и Results Appendix. Полная матрица с файлами и действиями — jury/REQUIREMENTS.md.'),
  table([['Требование','Реализация'],['Настраиваемый чек-лист','Формулировки, веса, шкалы, N/A, новые критерии и версии через UI'],['Оценка RU KZ EN','Основной анализ транскрипта; бот и события служат контекстом'],['Объяснения и доказательства','Ссылки на исходные реплики, проверка значений и текста цитат'],['Карточка и звонки','Просмотр диалога, плеер, переход к участку записи'],['Апелляция и пересмотр','Комментарий, причина решения, исходная и финальная оценки'],['Замена критерия','Новая версия конфигурации применяется новыми заданиями'],['DEV Results JSON 1.0','65 записей ok; ID, типы, границы и арифметика проверены'],['Контроль и Git','FBroker: 10/10, PROD проверен. Код и оба файла опубликованы в GitHub']],[155,350]),
  p('Проверка поставки','h'),p('Команда <b>python jury/check_package.py</b> сверяет SHA-256 файлов, схему DEV, ID, границы номеров реплик и арифметику. Для переносимой проверки опубликованы только ID, канал, язык и количество реплик. Проверка смысла и подлинности источника требует оригинальных данных.'),
  p('Условия сдачи','h'),p('По правилам нужны открытый репозиторий, README и результаты DEV и PROD до стоп-кода. Локальная папка, архив или commit без push не завершают сдачу. В Git опубликованы DEV 65/65 и PROD FBroker 10/10. Swap из трёх чатов сохранён без оценки; он не включён в PROD.'),PageBreak()]
 story += [p('Эксперименты и качество','title'),
  table([['Проверка','Наблюдение','Ограничение'],['Полный DEV','65/65; RU 35, KZ 15, EN 15','Покрытие, не точность'],['Ранний пилот','45/48 совпадений на 6 диалогах','Предварительная разметка ассистента, не человеческий эталон'],['low против medium','3 ID; среднее 4,60 и 5,76 с','По одному проходу, без рандомизации'],['ASR до и после DSP','5 звонков; 86 пар Whisper; 10 успешных запросов Gemini','WER/CER требуют ручного эталона']],[125,185,195]),
  p('Различаем наблюдения и выводы','h'),p('В полном DEV сохранены 51 блок резюме и рекомендаций и 54 разбора вопросов. Дополнительный блок может не пройти проверку при сохранённом основном балле. В журнале видны неудачные попытки и повторы; они не исключаются из истории.'),
  p('Русский и казахский в одной записи','h'),p('Gemini получает исходный и очищенный сигнал отдельными запросами без готового транскрипта. Локальная базовая модель — Whisper tiny INT8. После очистки встречаются ошибки казахских слов; автоматически считать очищенный вариант лучшим нельзя. На сайте есть ручной эталон, WER/CER и экспорт сравнения.'),
  p('Звук не доказывает намерение','h'),p('Паузы, кашель, одновременная речь и интонационные признаки показываются как наблюдения для прослушивания. Тихий участок не доказывает игнорирование, кашель не является диагнозом, воспринимаемая манера речи не равна внутреннему эмоциональному состоянию.'),
  p('Денежная стоимость не определена: тарифы не заданы, часть usage неизвестна. Экономия времени, удержание и связь с CRM не измерены. Источники чисел: jury/evidence и документы VALIDATION, FULL_DEV_RUN, ANALYTICS_VALIDATION, ASR_VALIDATION.','small'),PageBreak()]
 story += [p('Защита и техническое интервью','title'),
  table([['Время','Действие'],['0:00–0:40','Проблема, пользователь и один выбранный диалог'],['0:40–2:10','Оценка, вес, N/A, доказательство и переход к реплике'],['2:10–3:10','Апелляция, причина решения и пересчитанный результат'],['3:10–4:10','Изменение критерия, новая версия и запуск задания'],['4:10–5:00','Файл DEV, тесты, один аудиоэкран и ограничения']],[115,390]),
  p('Что стоит объяснить самостоятельно','h'),p('<b>Где наша работа?</b> Правила, проверка ответа, расчёт, очередь, хранение и пересмотр. Используется готовая модель, разработка велась с AI-ассистентом. Личный вклад участник описывает только по действительно выполненным действиям.'),
  p('<b>Какая точность?</b> 65 обработанных диалогов не дают 100% точности. Ранние 45/48 относятся к малой выборке и разметке ассистента. Нужен независимый человеческий эталон и новые данные.'),
  p('<b>Что при ошибке?</b> Прежний результат сохраняется, состояние задания видно в очереди. Неопределённый запрос после перезапуска не повторяется молча; доступен явный повтор.'),
  p('Следующие инженерные шаги','h'),p('Собрать независимую разметку RU KZ EN и смешанной речи, измерить ошибки по критериям и пропуски грубых нарушений. Затем добавить проверенную базу знаний, управление доступом и правила хранения. Для бизнес-эффекта нужны измерения времени проверяющего или подтверждённые исходы CRM.'),
  p('Быстрый запуск из архива: START_DEMO.cmd → http://127.0.0.1:8766. Три чата синтетические, выводы получены правилами, не AI. Для реального анализа нужны официальный JSON и ключ выбранного провайдера.','small'),
  p('Источники требований: CQA Hackathon Student Guide v3, стр. 1–4; CQA Student Guide Appendix Results, стр. 1–3. Подробная инструкция и ответы: jury/DEMO_AND_QA.md.','small')]
 out=ROOT/'output/pdf/Freedom_CQA_Studio_Bibol_Jury.pdf';out.parent.mkdir(parents=True,exist_ok=True)
 SimpleDocTemplate(str(out),pagesize=A4,rightMargin=44,leftMargin=44,topMargin=48,bottomMargin=46,
  title='Freedom CQA Studio Материалы для жюри',author='Бибол Жайлыбаев',subject='Fantastic Four CQA hackathon technical review').build(story,onFirstPage=footer,onLaterPages=footer)
 (ROOT/'jury/Freedom_CQA_Studio_Jury.pdf').write_bytes(out.read_bytes());print(out)

if __name__=='__main__':main()
