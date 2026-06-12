import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
import base64, io, boto3
from sqlalchemy import create_engine, text
from datetime import datetime

dash.register_page(__name__, path='/connection-builder')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
s3_client = boto3.client('s3', endpoint_url="http://localhost:9000", aws_access_key_id="minio_admin",
                         aws_secret_access_key="minio_password")
engine = create_engine(POSTGRES_URI)
RAW_BUCKET = "raw-uploads"


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
        dbc.NavItem(dbc.NavLink("Загрузка файла", active=True, href="#")),
        dbc.NavItem(dbc.NavLink("Создание датасета", href=f"/dataset-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Конструктор чартов", href=f"/chart-builder?ws_id={ws_id}")),
    ], pills=True, className="mb-4")

    return dbc.Container([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='raw-file-store'),
        nav,
        html.H3("Новое подключение", className="mb-4 text-dark"),
        dbc.Card([
            dbc.CardBody([
                dbc.Label("Название подключения:"),
                dbc.Input(id="connection-name-input", type="text", className="mb-4"),
                dcc.Upload(
                    id='upload-raw-data', children=html.Div(['Перетащите файл Excel/CSV сюда']),
                    style={'width': '100%', 'height': '80px', 'lineHeight': '80px', 'borderStyle': 'dashed',
                           'borderRadius': '10px', 'textAlign': 'center', 'cursor': 'pointer',
                           'backgroundColor': '#f8f9fa'}, multiple=False
                ),
                html.Div(id='sheet-selection-container', style={'display': 'none'}, children=[
                    dbc.Label("Выберите листы для сохранения:", className="mt-4 text-primary fw-bold"),
                    dcc.Dropdown(id='raw-sheet-select', multi=True, className="mb-3")
                ]),
                html.Div(id='connection-preview-container', className="mt-4"),
                dbc.Button("Сохранить", id="btn-save-connection", color="success", className="mt-4 w-100",
                           style={'display': 'none'}),
                html.Div(id='upload-raw-status', className="mt-3 fw-bold text-center")
            ])
        ], className="shadow-sm")
    ], className="mt-4")


@callback(
    Output('raw-file-store', 'data'), Output('sheet-selection-container', 'style'),
    Output('raw-sheet-select', 'options'),
    Output('raw-sheet-select', 'value'), Output('connection-preview-container', 'children'),
    Output('btn-save-connection', 'style'),
    Input('upload-raw-data', 'contents'), State('upload-raw-data', 'filename'), prevent_initial_call=True
)
def handle_upload(contents, filename):
    if not contents: return None, {'display': 'none'}, [], [], "", {'display': 'none'}
    decoded = base64.b64decode(contents.split(',')[1])
    is_excel = filename.endswith(('.xlsx', '.xls'))
    try:
        if is_excel:
            xl = pd.ExcelFile(io.BytesIO(decoded))
            sheets = xl.sheet_names
            val = [sheets[0]] if sheets else []
            df_preview = pd.read_excel(io.BytesIO(decoded), sheet_name=val[0], nrows=20) if val else pd.DataFrame()
        else:
            sheets, val = [], []
            df_preview = pd.read_csv(io.StringIO(decoded.decode('utf-8')), nrows=20)

        table = dash_table.DataTable(data=df_preview.to_dict('records'),
                                     columns=[{'name': str(i), 'id': str(i)} for i in df_preview.columns],
                                     style_table={'overflowX': 'auto'},
                                     style_cell={'textAlign': 'left', 'padding': '8px'})
        return {'bytes': contents.split(',')[1], 'is_excel': is_excel, 'filename': filename}, {
            'display': 'block'} if is_excel else {'display': 'none'}, [{'label': s, 'value': s} for s in
                                                                       sheets], val, html.Div(
            [html.H6("Предпросмотр (20 строк):", className="text-success"), table]), {'display': 'block'}
    except Exception as e:
        return None, {'display': 'none'}, [], [], dbc.Alert(f"Ошибка: {e}", color="danger"), {'display': 'none'}


@callback(Output('connection-preview-container', 'children', allow_duplicate=True), Input('raw-sheet-select', 'value'),
          State('raw-file-store', 'data'), prevent_initial_call=True)
def update_preview(sheets, file_data):
    if not file_data or not file_data['is_excel'] or not sheets: return dash.no_update
    df_preview = pd.read_excel(io.BytesIO(base64.b64decode(file_data['bytes'])), sheet_name=sheets[0], nrows=20)
    return html.Div([html.H6(f"Предпросмотр '{sheets[0]}':"), dash_table.DataTable(data=df_preview.to_dict('records'),
                                                                                   columns=[
                                                                                       {'name': str(i), 'id': str(i)}
                                                                                       for i in df_preview.columns],
                                                                                   style_table={'overflowX': 'auto'},
                                                                                   style_cell={'textAlign': 'left',
                                                                                               'padding': '8px'})])


@callback(Output('upload-raw-status', 'children'), Output('upload-raw-status', 'className'),
          Input('btn-save-connection', 'n_clicks'), State('connection-name-input', 'value'),
          State('raw-sheet-select', 'value'), State('raw-file-store', 'data'), State('current-ws-id', 'data'),
          State('auth-state', 'data'), prevent_initial_call=True)
def save_conn(n_clicks, name, sheets, file_data, ws_id, auth_state):
    if not name: return "Укажите название", "text-danger mt-3"
    ensure_bucket(RAW_BUCKET)
    try:
        decoded = base64.b64decode(file_data['bytes'])
        timestamp, uname = datetime.now().strftime("%Y%m%d_%H%M%S"), auth_state.get('username', 'user')
        s_filename = file_data['filename'].replace(" ", "_")

        with engine.connect() as conn:
            if file_data['is_excel']:
                for s in sheets:
                    df = pd.ExcelFile(io.BytesIO(decoded)).parse(s)
                    csv_bytes = df.to_csv(index=False).encode('utf-8')
                    key = f"{uname}/{timestamp}_{str(s).replace(' ', '_')}_{s_filename}.csv"
                    s3_client.put_object(Bucket=RAW_BUCKET, Key=key, Body=csv_bytes)
                    conn.execute(text(
                        "INSERT INTO connections (user_id, workspace_id, name, raw_file_path) VALUES (:u, :w, :n, :p)"),
                                 {"u": auth_state['user_id'], "w": ws_id, "n": f"{name} ({s})",
                                  "p": f"{RAW_BUCKET}/{key}"})
            else:
                key = f"{uname}/{timestamp}_{s_filename}"
                s3_client.put_object(Bucket=RAW_BUCKET, Key=key, Body=decoded)
                conn.execute(text(
                    "INSERT INTO connections (user_id, workspace_id, name, raw_file_path) VALUES (:u, :w, :n, :p)"),
                             {"u": auth_state['user_id'], "w": ws_id, "n": name, "p": f"{RAW_BUCKET}/{key}"})
            conn.commit()
        return "Успешно сохранено!", "text-success mt-3"
    except Exception as e:
        return f"Ошибка: {e}", "text-danger mt-3"