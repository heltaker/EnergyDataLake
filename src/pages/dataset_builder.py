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


def layout(ws_id=None, **kwargs):
    if not ws_id: return dbc.Container([html.H4("Ошибка: ID области потерян", className="mt-5 text-danger"),
                                        dbc.Button("В профиль", href="/workspaces")])

    nav = dbc.Nav([
        dbc.NavItem(dbc.NavLink("← К объектам области", href=f"/workspace-view?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Загрузка файла", href=f"/connection-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Создание датасета", active=True, href="#")),
        dbc.NavItem(dbc.NavLink("Конструктор чартов", href=f"/chart-builder?ws_id={ws_id}")),
    ], pills=True, className="mb-4")

    return dbc.Container([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='temp-file-info'),
        nav,
        html.H3("Создание датасета", className="mb-4 text-dark"),
        dbc.Card([
            dbc.CardBody([
                dbc.Label("Выберите сырое подключение:"),
                dcc.Dropdown(id='connection-select', placeholder="Загрузка списка...")
            ])
        ], className="mb-4 shadow-sm"),

        dbc.Card(id='schema-panel', style={'display': 'none', 'overflow': 'visible'}, children=[
            dbc.CardHeader("Настройка полей", className="fw-bold text-success"),
            dbc.CardBody([
                dash_table.DataTable(
                    id='schema-table', editable=True,
                    columns=[
                        {'id': 'field', 'name': 'Поле (Колонка)', 'editable': False},
                        # Поле "Тип данных" теперь статично и недоступно для изменения пользователем (нет presentation='dropdown')
                        {'id': 'type', 'name': 'Тип данных', 'editable': False},
                        # Поле "Агрегация" редактируемо и имеет выпадающий список
                        {'id': 'agg', 'name': 'Агрегация', 'presentation': 'dropdown', 'editable': True}
                    ],
                    data=[],
                    # Все возможные варианты агрегаций для инициализации
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
                    # Ограничение вариантов агрегации в зависимости от типа данных строки
                    dropdown_conditional=[
                        {
                            'if': {
                                'column_id': 'agg',
                                'filter_query': '{type} eq "Строка" || {type} eq "Дата" || {type} eq "Дата и время" || {type} eq "Логический"'
                            },
                            'options': [{'label': i, 'value': i} for i in ['Нет', 'Количество', 'Количество уникальных']]
                        },
                        {
                            'if': {
                                'column_id': 'agg',
                                'filter_query': '{type} eq "Целое число" || {type} eq "Дробное число"'
                            },
                            'options': [{'label': i, 'value': i} for i in ['Количество', 'Среднее', 'Максимальное', 'Минимальное', 'Сумма']]
                        }
                    ],
                    # Стили предотвращения обрезки всплывающего списка (Drop-down Overflow Fix)
                    style_table={'overflowX': 'visible', 'overflowY': 'visible', 'minWidth': '100%'},
                    style_cell={'textAlign': 'left', 'padding': '10px', 'overflow': 'visible'},
                    style_data={'overflow': 'visible'},
                    css=[
                        {"selector": ".dash-spreadsheet", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-table-container", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-spreadsheet-container", "rule": "overflow: visible !important;"},
                        {"selector": "td.dash-cell", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-cell div", "rule": "overflow: visible !important;"},
                        {"selector": ".dash-dropdown", "rule": "overflow: visible !important;"},
                        {"selector": ".Select-menu-outer", "rule": "display: block !important; border: 1px solid #ccc !important; background-color: white !important; z-index: 9999 !important; position: absolute !important;"},
                        {"selector": ".Select", "rule": "overflow: visible !important;"}
                    ],
                ),
                html.Hr(),
                dbc.Label("Название датасета:"), dbc.Input(id="dataset-name-input", type="text", className="mb-3"),
                dbc.Button("Сохранить и обработать", id="btn-save-dataset", color="success", className="w-100"),
                html.Div(id='dataset-save-status', className="mt-3 fw-bold text-center")
            ], style={'overflow': 'visible'})
        ], className="shadow-sm")
    ], className="mt-4")


@callback(Output('connection-select', 'options'), Input('current-ws-id', 'data'))
def load_conns(ws_id):
    if not ws_id: return []
    with engine.connect() as conn:
        res = conn.execute(
            text("SELECT id, name, raw_file_path FROM connections WHERE workspace_id = :ws ORDER BY created_at DESC"),
            {"ws": ws_id}).mappings().all()
        return [{'label': r['name'], 'value': json.dumps({'id': r['id'], 'path': r['raw_file_path']})} for r in res]


@callback(Output('schema-panel', 'style'), Output('schema-table', 'data'), Output('temp-file-info', 'data'),
          Input('connection-select', 'value'), prevent_initial_call=True)
def load_schema(conn_json):
    if not conn_json: return {'display': 'none', 'overflow': 'visible'}, [], None
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
        return {'display': 'block', 'overflow': 'visible'}, schema, {'bytes': base64.b64encode(file_bytes).decode(),
                                                                     'conn_id': cdata['id']}
    except Exception as e:
        return {'display': 'none', 'overflow': 'visible'}, [], None


@callback(Output('dataset-save-status', 'children'), Output('dataset-save-status', 'className'),
          Input('btn-save-dataset', 'n_clicks'), State('dataset-name-input', 'value'), State('schema-table', 'data'),
          State('temp-file-info', 'data'), State('auth-state', 'data'), prevent_initial_call=True)
def save_ds(nc, name, schema, finfo, auth):
    if not name: return "Укажите имя", "text-danger"
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

        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO datasets (connection_id, name, columns_config, file_path) VALUES (:c, :n, :conf, :fp)"),
                         {"c": finfo['conn_id'], "n": name, "conf": json.dumps(schema, ensure_ascii=False),
                          "fp": f"{PROCESSED_BUCKET}/{key}"})
            conn.execute(text("UPDATE connections SET processed_file_path = :fp WHERE id = :c"),
                         {"fp": f"{PROCESSED_BUCKET}/{key}", "c": finfo['conn_id']})
            conn.commit()
        return "Датасет сохранен!", "text-success"
    except Exception as e:
        return f"Ошибка: {e}", "text-danger"