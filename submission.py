"""Offline export/check without model credentials: python submission.py --help."""
import argparse
import json
from pathlib import Path
import sys

from cqa.store import Store
from cqa.submission import build, snapshot, validate, write_document

ROOT = Path(__file__).resolve().parent


def reject_constant(value):
    raise ValueError('Недопустимое число ' + value)


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Повторяющееся поле JSON: ' + key)
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description='CQA Results JSON 1.0 для жюри')
    parser.add_argument('action', choices=['export', 'check'])
    parser.add_argument('file', nargs='?', help='Путь проверяемого JSON для check')
    parser.add_argument('--set', choices=['dev', 'prod'], required=True)
    parser.add_argument('--team', help='Зарегистрированное название команды')
    parser.add_argument('--group', help='Точная группа в SQLite; по умолчанию DEV / PROD')
    parser.add_argument('--db', type=Path, default=ROOT / 'data/cqa.sqlite')
    args = parser.parse_args()
    try:
        if not args.db.is_file():
            raise ValueError('Локальная база не найдена. Сначала импортируйте исходный набор')
        store = Store(args.db)
        group = args.group or args.set.upper()
        if args.action == 'check':
            if not args.file:
                raise ValueError('Укажите JSON-файл для проверки')
            document = json.loads(Path(args.file).read_text(encoding='utf-8'), parse_constant=reject_constant, object_pairs_hook=unique_fields)
            validate(document, snapshot(store, group)['records'], args.set)
            print(f'OK: {len(document["results"])} записей; ID, типы, доказательства и расчёт проверены')
        else:
            document, report = build(store, args.set, group, args.team)
            records = snapshot(store, group)['records']
            path = write_document(document, records, args.set, ROOT / report['relative_path'], ROOT / 'data/submission_backups')
            print(f'{path}\nУспешных: {report["ok"]}; error: {len(report["errors"])}. Файл сохранён локально; commit и push выполняются отдельно.')
    except (ValueError, OSError, KeyError) as error:
        print('Ошибка: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
