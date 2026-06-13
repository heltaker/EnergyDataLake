# Страница: конструктор/редактор чартов (path='/chart-builder')
import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
import io, boto3, json
from sqlalchemy import create_engine, text

dash.register_page(__name__, path='/chart-builder')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
s3_client = boto3.client('s3', endpoint_url="http://localhost:9000", aws_access_key_id="minio_admin",
                         aws_secret_access_key="minio_password")
engine = create_engine(POSTGRES_URI)


def layout(ws_id=None, chart_id=None, **kwargs):
    if not ws_id: return dbc.Container([html.H4("Ошибка: ID области потерян", className="mt-5 text-danger"),
                                        dbc.Button("В профиль", href="/workspaces")])

    # Режим редактирования: загружаем сохранённый чарт
    edit_prefill = None
    if chart_id:
        try:
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT id, dataset_id, name, chart_type, x_axis, y_axis FROM charts WHERE id = :id"),
                    {"id": int(chart_id)}).mappings().first()
            if row:
                edit_prefill = {'chart_id': row['id'], 'dataset_id': row['dataset_id'], 'name': row['name'],
                                't': row['chart_type'], 'x': row['x_axis'], 'y': row['y_axis']}
        except Exception as e:
            print(f"Ошибка загрузки чарта: {e}")

    nav = dbc.Nav([
        dbc.NavItem(dbc.NavLink("← К объектам области", href=f"/workspace-view?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Загрузка файла", href=f"/connection-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Создание датасета", href=f"/dataset-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Конструктор чартов", active=True, href="#")),
    ], pills=True, className="mb-4")

    title = "Редактирование графика" if edit_prefill else "Конструктор графиков"

    return dbc.Container([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='current-dataset-config'),
        dcc.Store(id='edit-chart-id', data=edit_prefill['chart_id'] if edit_prefill else None),
        dcc.Store(id='edit-chart-prefill', data=edit_prefill),
        nav,
        html.H3(title, className="mb-4 text-dark"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Настройки", className="fw-bold"),
                    dbc.CardBody([
                        dbc.Label("Датасет:"), dcc.Dropdown(id='chart-dataset-select', className="mb-3"),
                        dbc.Label("Тип графика:"), dcc.Dropdown(id='chart-type-select', options=[
                            {'label': 'Линейная диаграмма', 'value': 'line'},
                            {'label': 'Столбчатая диаграмма', 'value': 'bar'},
                            {'label': 'Точечная диаграмма', 'value': 'scatter'},
                            {'label': 'Круговая диаграмма', 'value': 'pie'}
                        ], value='bar', clearable=False, className="mb-3"),

                        dbc.Label("Ось X:", id="label-x", className="mb-1"),
                        dcc.Dropdown(id='chart-x-select', className="mb-3"),

                        dbc.Label("Ось Y:", id="label-y", className="mb-1"),
                        dcc.Dropdown(id='chart-y-select', className="mb-4"),

                        html.Hr(),
                        dbc.Label("Имя графика:"),
                        dbc.Input(id="chart-name-input", type="text", className="mb-2",
                                  value=edit_prefill['name'] if edit_prefill else None),
                        dbc.Button("Сохранить", id="btn-save-chart", color="primary", className="w-100"),
                        html.Div(id='chart-save-status', className="mt-2 text-center")
                    ])
                ], className="shadow-sm")
            ], width=3),
            dbc.Col([dbc.Card(dbc.CardBody(dcc.Graph(id='main-chart-canvas', style={'height': '70vh'})),
                              className="shadow-sm")], width=9)
        ])
    ], className="mt-4")


# Динамическое изменение подписей параметров в левой панели в зависимости от типа графика
@callback(
    Output('label-x', 'children'),
    Output('label-y', 'children'),
    Input('chart-type-select', 'value')
)
def update_axis_labels(chart_type):
    if chart_type == 'pie':
        return "Категория:", "Параметр:"
    return "Ось X:", "Ось Y:"


@callback(Output('chart-dataset-select', 'options'), Output('chart-dataset-select', 'value'),
          Input('current-ws-id', 'data'), State('edit-chart-prefill', 'data'))
def load_ds(ws_id, edit_prefill):
    if not ws_id: return [], dash.no_update
    with engine.connect() as conn:
        res = conn.execute(text(
            "SELECT d.id, d.name, d.columns_config, d.file_path FROM datasets d JOIN connections c ON d.connection_id = c.id WHERE c.workspace_id = :ws"),
            {"ws": ws_id}).mappings().all()
        options = [{'label': r['name'], 'value': json.dumps(dict(r))} for r in res]

    value = dash.no_update
    if edit_prefill:
        for o in options:
            if json.loads(o['value'])['id'] == edit_prefill['dataset_id']:
                value = o['value']
                break
    return options, value


@callback(
    Output('chart-x-select', 'options'), Output('chart-y-select', 'options'), Output('current-dataset-config', 'data'),
    Input('chart-dataset-select', 'value'), prevent_initial_call=True
)
def update_axes(ds_json):
    if not ds_json: return [], [], None
    ds_data = json.loads(ds_json)
    c_config = ds_data['columns_config']
    if isinstance(c_config, str): c_config = json.loads(c_config)
    ds_data['columns_config'] = c_config

    x_opts = [{'label': c['field'], 'value': c['field']} for c in c_config]

    y_opts = []
    for c in c_config:
        is_numeric = c['type'] in ['Число', 'Дробное число', 'Целое число']
        has_agg = c.get('agg', 'Нет') != 'Нет'
        if is_numeric or has_agg:
            y_opts.append({'label': c['field'], 'value': c['field']})

    return x_opts, y_opts, ds_data


# Восстановление настроек сохранённого чарта (срабатывает один раз после загрузки датасета)
@callback(
    Output('chart-type-select', 'value'),
    Output('chart-x-select', 'value'),
    Output('chart-y-select', 'value'),
    Output('edit-chart-prefill', 'data'),
    Input('current-dataset-config', 'data'),
    State('edit-chart-prefill', 'data'),
    prevent_initial_call=True
)
def apply_edit_prefill(ds_data, edit_prefill):
    if not ds_data or not edit_prefill:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    return edit_prefill['t'], edit_prefill['x'], edit_prefill['y'], None


@callback(Output('main-chart-canvas', 'figure'), Input('current-dataset-config', 'data'),
          Input('chart-type-select', 'value'), Input('chart-x-select', 'value'), Input('chart-y-select', 'value'),
          prevent_initial_call=True)
def draw(ds_data, t, x, y):
    if not ds_data or not x or not y: return {}
    try:
        bucket, key = ds_data['file_path'].split('/', 1)
        df = pd.read_parquet(io.BytesIO(s3_client.get_object(Bucket=bucket, Key=key)['Body'].read()))

        agg_label = 'Сумма'
        agg_func = 'sum'
        for c in ds_data['columns_config']:
            if c['field'] == y:
                agg_label = c.get('agg', 'Сумма')
                agg_func = {
                    "Сумма": "sum",
                    "Количество": "count",
                    "Количество уникальных": "nunique",
                    "Максимальное": "max",
                    "Минимальное": "min",
                    "Среднее": "mean"
                }.get(agg_label, 'sum')
                break

        df_g = df.groupby(x, as_index=False)[y].agg(agg_func)

        # Сортировка по алфавиту
        df_g = df_g.sort_values(by=x, ascending=True)

        if len(df_g) > 50 and t in ['bar', 'line']:
            df_g = df_g.head(50)

        if t == 'bar':
            fig = px.bar(df_g, x=x, y=y)
        elif t == 'line':
            fig = px.line(df_g, x=x, y=y, markers=True)
        elif t == 'scatter':
            fig = px.scatter(df_g, x=x, y=y)
        elif t == 'pie':
            fig = px.pie(df_g, names=x, values=y)
            fig.update_traces(
                textinfo='none',
                hovertemplate="<b>%{label}</b><br>Значение: %{value}<br>Доля: %{percent}<extra></extra>"
            )

        fig.update_layout(margin={'l': 40, 'b': 80, 't': 50, 'r': 20}, template='plotly_white')
        return fig
    except Exception as e:
        return {}


@callback(Output('chart-save-status', 'children'), Output('chart-save-status', 'className'),
          Input('btn-save-chart', 'n_clicks'), State('chart-name-input', 'value'), State('chart-type-select', 'value'),
          State('chart-x-select', 'value'), State('chart-y-select', 'value'), State('current-dataset-config', 'data'),
          State('edit-chart-id', 'data'),
          prevent_initial_call=True)
def save(nc, n, t, x, y, ds, edit_chart_id):
    if not n: return "Укажите имя", "text-danger mt-2"
    if not ds or not x or not y: return "Выберите датасет и оси", "text-danger mt-2"
    try:
        with engine.connect() as conn:
            if edit_chart_id:
                # Обновление чарта - устанавливаем updated_at = CURRENT_TIMESTAMP
                conn.execute(text(
                    "UPDATE charts SET dataset_id = :d, name = :n, chart_type = :t, x_axis = :x, y_axis = :y, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :id"),
                    {"d": ds['id'], "n": n, "t": t, "x": x, "y": y, "id": edit_chart_id})
                conn.commit()
                return "Изменения сохранены!", "text-success mt-2"
            else:
                # Новая запись: инициализируем created_at и updated_at
                conn.execute(
                    text("INSERT INTO charts (dataset_id, name, chart_type, x_axis, y_axis, created_at, updated_at) "
                         "VALUES (:d, :n, :t, :x, :y, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"d": ds['id'], "n": n, "t": t, "x": x, "y": y})
                conn.commit()
                return "Успешно сохранено!", "text-success mt-2"
    except Exception as e:
        return f"Ошибка БД: {e}", "text-danger mt-2"