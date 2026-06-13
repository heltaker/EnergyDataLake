# Страница: создание/редактирование датасета (path='/dataset-builder')
import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
import base64, io, boto3, json
from sqlalchemy import create_engine, text
from datetime import datetime

dash.register_page(__name__, path='/dataset-builder')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
s3_client = boto3.client('s3', endpoint_url="http://localhost:9000", aws_access_key_id="minio_admin",
                         aws_secret_access_key="minio_password")
engine = create_engine(POSTGRES_URI)
PROCESSED_BUCKET = "processed-datasets"


def ensure_bucket(bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except:
        s3_client.create_bucket(Bucket=bucket_name)


def layout(ws_id=None, ds_id=None, **kwargs):
    if not ws_id: return dbc.Container([html.H4("Ошибка: ID области потерян", className="mt-5 text-danger"),
                                        dbc.Button("В профиль", href="/workspaces")])

    # Режим редактирования: загружаем сохранённый датасет
    edit_data = None
    if ds_id:
        try:
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT d.id, d.name, d.columns_config, d.file_path, d.connection_id, c.raw_file_path "
                    "FROM datasets d JOIN connections c ON d.connection_id = c.id WHERE d.id = :id"),
                    {"id": int(ds_id)}).mappings().first()
            if row:
                cfg = row['columns_config']
                if isinstance(cfg, str): cfg = json.loads(cfg)
                edit_data = {
                    'id': row['id'], 'name': row['name'], 'config': cfg,
                    'file_path': row['file_path'], 'conn_id': row['connection_id'],
                    'conn_value': json.dumps({'id': row['connection_id'], 'path': row['raw_file_path']})
                }
        except Exception as e:
            print(f"Ошибка загрузки датасета: {e}")

    nav = dbc.Nav([
        dbc.NavItem(dbc.NavLink("К объектам области", href=f"/workspace-view?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Загрузка файла", href=f"/connection-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Создание датасета", active=True, href="#")),
        dbc.NavItem(dbc.NavLink("Конструктор чартов", href=f"/chart-builder?ws_id={ws_id}")),
    ], pills=True, className="mb-4")

    title = "Редактирование датасета" if edit_data else "Создание датасета"

    return dbc.Container([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='temp-file-info'),
        dcc.Store(id='edit-ds-id', data=edit_data['id'] if edit_data else None),
        dcc.Store(id='edit-ds-prefill', data=edit_data),
        nav,

        # Заголовок страницы
        dbc.Row([
            dbc.Col([
                html.H3(title, className="fw-extrabold text-dark mb-1"),
                html.P("Настройте схему полей и примените агрегации к сырым данным", className="text-muted small mb-0")
            ], width=12)
        ], className="mb-4 bg-white p-3 rounded-3 shadow-sm border"),

        # Метаданные: название датасета вынесено вверх и его высота стандартизирована
        # Кнопка сохранения расположена гармонично ниже названия и подключения
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Название датасета:", className="fw-bold text-secondary small uppercase mb-2"),
                        dbc.Input(id="dataset-name-input", type="text", placeholder="Введите название датасета...",
                                  className="mb-3 border shadow-none",  # Обычный стандартный класс высоты
                                  value=edit_data['name'] if edit_data else None),
                    ], width=7),
                    dbc.Col([
                        dbc.Label("Выберите сырое подключение:",
                                  className="fw-bold text-secondary small uppercase mb-2"),
                        dcc.Dropdown(id='connection-select', placeholder="Выберите источник данных...",
                                     className="shadow-none mb-3")
                    ], width=5)
                ]),

                # Кнопка сохранения расположена прямо под метаданными
                dbc.Row([
                    dbc.Col([
                        dbc.Button(
                            "Сохранить и обработать",
                            id="btn-save-dataset", color="success", className="px-4 py-2 shadow-sm fw-bold w-100 mb-2"
                        )
                    ], width=12)
                ])
            ], className="bg-light border-0")
        ], className="mb-4 shadow-sm border-0 rounded-3"),

        html.Div(id='dataset-save-status', className="mt-2 mb-3 fw-bold text-center"),

        # Схема полей
        dbc.Card(id='schema-panel', style={'display': 'none', 'overflow': 'visible'}, children=[
            dbc.CardHeader("Настройка полей и типов агрегаций", className="fw-bold text-dark bg-white border-bottom"),
            dbc.CardBody([
                dash_table.DataTable(
                    id='schema-table', editable=True,
                    columns=[
                        {'id': 'field', 'name': 'Поле (Колонка)', 'editable': False},
                        {'id': 'type', 'name': 'Тип данных', 'editable': False},
                        {'id': 'agg', 'name': 'Агрегация', 'presentation': 'dropdown', 'editable': True}
                    ],
                    data=[],
                    dropdown={
                        'agg': {
                            'options': [{'label': i, 'value': i} for i in [
                                'Нет',
                                'Количество',
                                'Количество уникальных',
                                'Среднее',
                                'Максимальное',
                                'Минимальное',
                                'Сумма'
                            ]]
                        }
                    },
                    dropdown_conditional=[
                        {
                            'if': {
                                'column_id': 'agg',
                                'filter_query': '{type} eq "Строка" || {type} eq "Дата" || {type} eq "Дата и время" || {type} eq "Логический"'
                            },
                            'options': [{'label': i, 'value': i} for i in
                                        ['Нет', 'Количество', 'Количество уникальных']]
                        },
                        {
                            'if': {
                                'column_id': 'agg',
                                'filter_query': '{type} eq "Целое число" || {type} eq "Дробное число"'
                            },
                            'options': [{'label': i, 'value': i} for i in
                                        ['Количество', 'Среднее', 'Максимальное', 'Минимальное', 'Сумма']]
                        }
                    ],
                    style_table={'overflowX': 'visible', 'overflowY': 'visible', 'minWidth': '100%'},
                    style_cell={'textAlign': 'left', 'padding': '12px', 'overflow': 'visible', 'fontFamily': 'inherit'},
                    style_data={'overflow': 'visible'},
                    style_header={'backgroundColor': '#f8f9fa', 'fontWeight': 'bold', 'color': '#495057'},
                    css=[
                        {"selector": ".dash-spreadsheet", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-table-container", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-spreadsheet-container", "rule": "overflow: visible !important;"},
                        {"selector": "td.dash-cell", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-cell div", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-dropdown", "rule": "overflow: visible !important;"},
                        {"selector": ".Select-menu-outer",
                         "rule": "display: block !important; border: 1px solid #ccc !important; background-color: white !important; z-index: 9999 !important; position: absolute !important;"},
                        {"selector": ".Select", "rule": "overflow: visible !important;"}
                    ],
                ),
            ], style={'overflow': 'visible'})
        ], className="shadow-sm border-0 rounded-3")
    ], className="mt-4")


@callback(Output('connection-select', 'options'), Output('connection-select', 'value'),
          Input('current-ws-id', 'data'), State('edit-ds-prefill', 'data'))
def load_conns(ws_id, edit_data):
    if not ws_id: return [], dash.no_update
    with engine.connect() as conn:
        res = conn.execute(
            text("SELECT id, name, raw_file_path FROM connections WHERE workspace_id = :ws ORDER BY created_at DESC"),
            {"ws": ws_id}).mappings().all()
        options = [{'label': r['name'], 'value': json.dumps({'id': r['id'], 'path': r['raw_file_path']})} for r in res]

    value = dash.no_update
    if edit_data:
        for o in options:
            if json.loads(o['value'])['id'] == edit_data['conn_id']:
                value = o['value']
                break
    return options, value


@callback(Output('schema-panel', 'style'), Output('schema-table', 'data'), Output('temp-file-info', 'data'),
          Output('edit-ds-prefill', 'data'),
          Input('connection-select', 'value'), State('edit-ds-prefill', 'data'), prevent_initial_call=True)
def load_schema(conn_json, edit_data):
    if not conn_json: return {'display': 'none', 'overflow': 'visible'}, [], None, dash.no_update
    cdata = json.loads(conn_json)
    try:
        bucket, key = cdata['path'].split('/', 1)
        file_bytes = s3_client.get_object(Bucket=bucket, Key=key)['Body'].read()
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=10)

        schema = []
        for col in df.columns:
            cs = str(col).lower()
            if any(k in cs for k in ['id', 'year', 'год', 'name', 'url', 'country', 'status']):
                t, a = 'Строка', 'Нет'
            elif pd.api.types.is_numeric_dtype(df[col]):
                t, a = ('Дробное число' if pd.api.types.is_float_dtype(df[col]) else 'Целое число'), 'Сумма'
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                t, a = 'Дата и время', 'Нет'
            else:
                t, a = 'Строка', 'Нет'
            schema.append({'field': col, 'type': t, 'agg': a})

        if edit_data and edit_data.get('conn_id') == cdata['id']:
            saved = {c['field']: c for c in edit_data.get('config', [])}
            for row in schema:
                if row['field'] in saved:
                    row['type'] = saved[row['field']].get('type', row['type'])
                    row['agg'] = saved[row['field']].get('agg', row['agg'])

        return {'display': 'block', 'overflow': 'visible'}, schema, {'bytes': base64.b64encode(file_bytes).decode(),
                                                                     'conn_id': cdata['id']}, None
    except Exception as e:
        return {'display': 'none', 'overflow': 'visible'}, [], None, dash.no_update


@callback(Output('dataset-save-status', 'children'), Output('dataset-save-status', 'className'),
          Input('btn-save-dataset', 'n_clicks'), State('dataset-name-input', 'value'), State('schema-table', 'data'),
          State('temp-file-info', 'data'), State('auth-state', 'data'), State('edit-ds-id', 'data'),
          prevent_initial_call=True)
def save_ds(nc, name, schema, finfo, auth, edit_ds_id):
    if not name: return "Укажите название датасета!", "text-danger"
    if not finfo: return "Сначала выберите сырое подключение!", "text-danger"
    ensure_bucket(PROCESSED_BUCKET)
    try:
        df = pd.read_csv(io.BytesIO(base64.b64decode(finfo['bytes'])))
        for r in schema:
            c = r['field']
            if r['type'] == 'Строка':
                df[c] = df[c].astype(str)
            elif r['type'] in ['Дробное число', 'Целое число']:
                df[c] = pd.to_numeric(df[c], errors='coerce')

        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        key = f"{auth['username']}/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name.replace(' ', '_')}.parquet"
        s3_client.put_object(Bucket=PROCESSED_BUCKET, Key=key, Body=buf.getvalue())
        new_fp = f"{PROCESSED_BUCKET}/{key}"

        with engine.begin() as conn:
            if edit_ds_id:
                old_fp = conn.execute(text("SELECT file_path FROM datasets WHERE id = :id"),
                                      {"id": edit_ds_id}).scalar()
                conn.execute(text(
                    "UPDATE datasets SET connection_id = :c, name = :n, columns_config = :conf, file_path = :fp, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :id"),
                    {"c": finfo['conn_id'], "n": name,
                     "conf": json.dumps(schema, ensure_ascii=False), "fp": new_fp, "id": edit_ds_id})
                conn.execute(text(
                    "UPDATE connections SET processed_file_path = :fp, updated_at = CURRENT_TIMESTAMP WHERE id = :c"),
                             {"fp": new_fp, "c": finfo['conn_id']})
                if old_fp and old_fp != new_fp:
                    _s3_delete(old_fp)
                return "Датасет успешно сохранен и обновлён!", "text-success"
            else:
                conn.execute(text(
                    "INSERT INTO datasets (connection_id, name, columns_config, file_path, created_at, updated_at) "
                    "VALUES (:c, :n, :conf, :fp, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"c": finfo['conn_id'], "n": name, "conf": json.dumps(schema, ensure_ascii=False),
                     "fp": new_fp})
                conn.execute(text(
                    "UPDATE connections SET processed_file_path = :fp, updated_at = CURRENT_TIMESTAMP WHERE id = :c"),
                             {"fp": new_fp, "c": finfo['conn_id']})
                return "Новый датасет успешно создан и обработан!", "text-success"
    except Exception as e:
        return f"Системная ошибка: {e}", "text-danger"