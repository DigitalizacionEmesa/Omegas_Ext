import argparse
import csv
import json
import os
from pathlib import Path

import pyodbc


DB_NAME = 'DataLakeSCCZ'
DEFAULT_CSV = 'ES1 seq. - mat.csv'
DEFAULT_DRIVERS = [
    'ODBC Driver 18 for SQL Server',
    'ODBC Driver 17 for SQL Server',
    'ODBC Driver 13 for SQL Server',
    'SQL Server Native Client 11.0',
    'SQL Server',
]
DEFAULT_SERVERS = ['172.16.10.10', 'EMEBIDWH']
DEFAULT_DB_USER = 'sccz'
DEFAULT_DB_PASSWORD = 'S@vera,CZ,2024'


def parse_args():
    parser = argparse.ArgumentParser(
        description='Sincroniza OB.Omegas a partir de un CSV con upsert por Assy.'
    )
    parser.add_argument(
        '--csv',
        default=DEFAULT_CSV,
        help='Ruta al CSV origen. Por defecto usa ES1 seq. - mat.csv',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Aplica cambios en base de datos. Sin este flag solo hace simulación.',
    )
    return parser.parse_args()


def unique_preserve_order(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def load_connection_config(project_root):
    config = {
        'drivers': list(DEFAULT_DRIVERS),
        'servers': list(DEFAULT_SERVERS),
    }

    config_path = project_root / 'db_connection_config.json'
    if config_path.exists():
        with config_path.open('r', encoding='utf-8') as fh:
            raw = json.load(fh)
        config['drivers'] = unique_preserve_order(raw.get('drivers', []) + config['drivers'])
        config['servers'] = unique_preserve_order(raw.get('cz_servers', []) + config['servers'])

    env_drivers = [item.strip() for item in os.getenv('OMEGAS_DB_DRIVERS', '').split(',') if item.strip()]
    env_servers = [item.strip() for item in os.getenv('OMEGAS_DB_CZ_SERVERS', '').split(',') if item.strip()]
    if env_drivers:
        config['drivers'] = unique_preserve_order(env_drivers + config['drivers'])
    if env_servers:
        config['servers'] = unique_preserve_order(env_servers + config['servers'])

    return config


def connect_to_cz_database(project_root):
    config = load_connection_config(project_root)
    db_user = os.getenv('OMEGAS_DB_USER_CZ', DEFAULT_DB_USER)
    db_password = os.getenv('OMEGAS_DB_PASSWORD_CZ', DEFAULT_DB_PASSWORD)
    installed_drivers = set(pyodbc.drivers())

    last_error = None
    for server in config['servers']:
        for driver in config['drivers']:
            if installed_drivers and driver not in installed_drivers:
                continue
            conn_str = (
                f'DRIVER={{{driver}}};'
                f'SERVER={server};'
                f'DATABASE={DB_NAME};'
                f'UID={db_user};PWD={db_password};'
                'TrustServerCertificate=yes;'
            )
            try:
                conn = pyodbc.connect(conn_str, timeout=5)
                print(f'[OK] Conectado a {DB_NAME} con server={server}, driver={driver}')
                return conn
            except Exception as exc:
                last_error = exc

    raise RuntimeError(f'No se pudo conectar a {DB_NAME}: {last_error}')


def normalize_value(value):
    if value is None:
        return None
    value = str(value).strip()
    if value in {'', '-'}:
        return None
    return value


def normalize_csv_row(row):
    return {
        'Assy': normalize_value(row.get('Assy')),
        'Beam': normalize_value(row.get('Beam')),
        'IF1': normalize_value(row.get('IF1')),
        'IF2': normalize_value(row.get('IF2')),
        'W/C': normalize_value(row.get('W/C')),
        'OmegaType': normalize_value(row.get('GRP_OMEGA_BRACKET_TYPE')),
    }


def load_csv_rows(csv_path):
    rows_by_assy = {}
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for raw_row in reader:
            row = normalize_csv_row(raw_row)
            assy = row['Assy']
            wc = row['W/C']
            if not assy or not wc:
                continue
            rows_by_assy[assy] = row
    return rows_by_assy


def load_existing_omegas(cursor):
    cursor.execute(
        """
        SELECT OmegaID, Assy, Beam, IF1, IF2, [W/C], ExtenderVariable, OmegaType
        FROM OB.Omegas
        """
    )
    result = {}
    for row in cursor.fetchall():
        result[row.Assy.strip()] = {
            'OmegaID': row.OmegaID,
            'Assy': normalize_value(row.Assy),
            'Beam': normalize_value(row.Beam),
            'IF1': normalize_value(row.IF1),
            'IF2': normalize_value(row.IF2),
            'W/C': normalize_value(getattr(row, 'W/C')),
            'ExtenderVariable': normalize_value(row.ExtenderVariable),
            'OmegaType': normalize_value(row.OmegaType),
        }
    return result


def compute_changes(csv_rows, existing_rows):
    updatable_columns = ['Beam', 'IF1', 'IF2', 'W/C', 'OmegaType']
    inserts = []
    updates = []
    unchanged = 0

    for assy, csv_row in csv_rows.items():
        existing = existing_rows.get(assy)
        if existing is None:
            inserts.append(csv_row)
            continue

        changed_fields = {}
        for column in updatable_columns:
            if existing.get(column) != csv_row.get(column):
                changed_fields[column] = {
                    'old': existing.get(column),
                    'new': csv_row.get(column),
                }

        if changed_fields:
            updates.append({
                'Assy': assy,
                'OmegaID': existing['OmegaID'],
                'changes': changed_fields,
                'row': csv_row,
                'extender_variable': existing.get('ExtenderVariable'),
            })
        else:
            unchanged += 1

    return inserts, updates, unchanged


def print_summary(inserts, updates, unchanged):
    print('')
    print('Resumen de sincronización')
    print('--------------------------')
    print(f'Insert nuevos: {len(inserts)}')
    print(f'Updates: {len(updates)}')
    print(f'Sin cambios: {unchanged}')

    if updates:
        print('')
        print('Primeros updates detectados:')
        for item in updates[:10]:
            change_text = ', '.join(
                f"{field}: {repr(values['old'])} -> {repr(values['new'])}"
                for field, values in item['changes'].items()
            )
            print(f"- {item['Assy']}: {change_text}")

    if inserts:
        print('')
        print('Primeros inserts detectados:')
        for item in inserts[:10]:
            print(
                f"- {item['Assy']} | W/C={item['W/C']} | Beam={item['Beam']} | "
                f"IF1={item['IF1']} | IF2={item['IF2']} | OmegaType={item['OmegaType']}"
            )


def apply_changes(conn, inserts, updates):
    cursor = conn.cursor()

    for item in updates:
        row = item['row']
        cursor.execute(
            """
            UPDATE OB.Omegas
            SET Beam = ?,
                IF1 = ?,
                IF2 = ?,
                [W/C] = ?,
                OmegaType = ?
            WHERE Assy = ?
            """,
            row['Beam'],
            row['IF1'],
            row['IF2'],
            row['W/C'],
            row['OmegaType'],
            row['Assy'],
        )

    for row in inserts:
        cursor.execute(
            """
            INSERT INTO OB.Omegas (Assy, Beam, IF1, IF2, [W/C], ExtenderVariable, OmegaType)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            row['Assy'],
            row['Beam'],
            row['IF1'],
            row['IF2'],
            row['W/C'],
            None,
            row['OmegaType'],
        )

    conn.commit()


def main():
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = project_root / csv_path

    if not csv_path.exists():
        raise FileNotFoundError(f'No existe el CSV: {csv_path}')

    csv_rows = load_csv_rows(csv_path)
    print(f'[INFO] Filas válidas leídas desde CSV: {len(csv_rows)}')

    with connect_to_cz_database(project_root) as conn:
        existing_rows = load_existing_omegas(conn.cursor())
        inserts, updates, unchanged = compute_changes(csv_rows, existing_rows)
        print_summary(inserts, updates, unchanged)

        if not args.apply:
            print('')
            print('Modo simulación: no se ha aplicado ningún cambio.')
            print('Ejecuta con --apply para grabar los updates/inserts en OB.Omegas.')
            return

        apply_changes(conn, inserts, updates)
        print('')
        print('[OK] Cambios aplicados correctamente en OB.Omegas.')


if __name__ == '__main__':
    main()