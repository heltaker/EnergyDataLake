# Страница: создание/редактирование подключения (path='/connection-builder')
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


def layout(ws_id=None, conn_id=None, **kwargs):
    if not ws_id: return dbc.Container([html.H4("Ошибка: ID области потерян", className="mt-5 text-danger"),
                                        dbc.Button("В профиль", href="/workspaces")])

    # Режим редактирования: загружаем сохранённое подключение
    edit_data, current_file_info = None, None
    if conn_id:
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT id, name, raw_file_path FROM connections WHERE id = :id"),
                                   {"id": int(conn_id)}).mappings().first()
            if row:
                edit_data = {'id': row['id'], 'name': row['name'], 'path': row['raw_file_path']}
                current_file_info = dbc.Alert([
                    html.B("Текущий файл: "), html.Code(row['raw_file_path'].split('/', 1)[1]),
                    html.Br(),
                    html.Small("Загрузите новый файл, чтобы заменить его, или просто измените название и сохраните.",
                               className="text-muted")
                ], color="light", className="mb-3 border")
        except Exception as e:
            print(f"Ошибка загрузки подключения: {e}")

    nav = dbc.Nav([
        dbc.NavItem(dbc.NavLink("← К объектам области", href=f"/workspace-view?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Загрузка файла", active=True, href="#")),
        dbc.NavItem(dbc.NavLink("Создание датасета", href=f"/dataset-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Конструктор чартов", href=f"/chart-builder?ws_id={ws_id}")),
    ], pills=True, className="mb-4")

    title = "Редактирование подключения" if edit_data else "Новое подключение"

    return dbc.Container([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='raw-file-store'),
        dcc.Store(id='edit-conn-data', data=edit_data),
        nav,
        html.H3(title, className="mb-4 text-dark"),
        dbc.Card([
            dbc.CardBody([
                dbc.Label("Название подключения:"),
                dbc.Input(id="connection-name-input", type="text", className="mb-4",
                          value=edit_data['name'] if edit_data else None),
                current_file_info if current_file_info else None,
                dcc.Upload(
                    id='upload-raw-data',
                    children=html.Div(['Перетащите файл Excel/CSV сюда' if not edit_data
                                       else 'Перетащите новый файл Excel/CSV сюда (замена текущего)']),
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
                           style={'display': 'block'} if edit_data else {'display': 'none'}),
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


def _delete_s3(full_path):
    try:
        if full_path:
            bucket, key = full_path.split('/', 1)
            s3_client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass


@callback(Output('upload-raw-status', 'children'), Output('upload-raw-status', 'className'),
          Input('btn-save-connection', 'n_clicks'), State('connection-name-input', 'value'),
          State('raw-sheet-select', 'value'), State('raw-file-store', 'data'), State('current-ws-id', 'data'),
          State('auth-state', 'data'), State('edit-conn-data', 'data'), prevent_initial_call=True)
def save_conn(n_clicks, name, sheets, file_data, ws_id, auth_state, edit_data):
    if not name: return "Укажите название", "text-danger mt-3"

    # ----- Режим редактирования существующего подключения -----
    if edit_data:
        try:
            with engine.connect() as conn:
                if file_data:
                    ensure_bucket(RAW_BUCKET)
                    decoded = base64.b64decode(file_data['bytes'])
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    uname = auth_state.get('username', 'user')
                    s_filename = file_data['filename'].replace(" ", "_")

                    if file_data['is_excel']:
                        if not sheets: return "Выберите лист", "text-danger mt-3"
                        s = sheets[0]
                        df = pd.ExcelFile(io.BytesIO(decoded)).parse(s)
                        body = df.to_csv(index=False).encode('utf-8')
                        key = f"{uname}/{timestamp}_{str(s).replace(' ', '_')}_{s_filename}.csv"
                    else:
                        body = decoded
                        key = f"{uname}/{timestamp}_{s_filename}"

                    s3_client.put_object(Bucket=RAW_BUCKET, Key=key, Body=body)
                    _delete_s3(edit_data['path'])
                    # Заменяем файл и обновляем updated_at
                    conn.execute(text("UPDATE connections SET name = :n, raw_file_path = :p, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                                 {"n": name, "p": f"{RAW_BUCKET}/{key}", "id": edit_data['id']})
                else:
                    # Только переименование - обновляем только name и updated_at
                    conn.execute(text("UPDATE connections SET name = :n, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                                 {"n": name, "id": edit_data['id']})
                conn.commit()
            return "Изменения сохранены!", "text-success mt-3"
        except Exception as e:
            return f"Ошибка: {e}", "text-danger mt-3"

    # ----- Создание нового подключения -----
    if not file_data: return "Загрузите файл", "text-danger mt-3"
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
                        "INSERT INTO connections (user_id, workspace_id, name, raw_file_path, created_at, updated_at) "
                        "VALUES (:u, :w, :n, :p, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                                 {"u": auth_state['user_id'], "w": ws_id, "n": f"{name} ({s})",
                                  "p": f"{RAW_BUCKET}/{key}"})
            else:
                key = f"{uname}/{timestamp}_{s_filename}"
                s3_client.put_object(Bucket=RAW_BUCKET, Key=key, Body=decoded)
                conn.execute(text(
                    "INSERT INTO connections (user_id, workspace_id, name, raw_file_path, created_at, updated_at) "
                    "VALUES (:u, :w, :n, :p, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                             {"u": auth_state['user_id'], "w": ws_id, "n": name, "p": f"{RAW_BUCKET}/{key}"})
            conn.commit()
        return "Успешно сохранено!", "text-success mt-3"
    except Exception as e:
        return f"Ошибка: {e}", "text-danger mt-3"