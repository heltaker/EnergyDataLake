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


def layout(ws_id=None, **kwargs):
    if not ws_id: return dbc.Container([html.H4("Ошибка: ID области потерян", className="mt-5 text-danger"),
                                        dbc.Button("В профиль", href="/workspaces")])

    nav = dbc.Nav([
        dbc.NavItem(dbc.NavLink("← К объектам области", href=f"/workspace-view?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Загрузка файла", href=f"/connection-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Создание датасета", href=f"/dataset-builder?ws_id={ws_id}")),
        dbc.NavItem(dbc.NavLink("Конструктор чартов", active=True, href="#")),
    ], pills=True, className="mb-4")

    return dbc.Container([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='current-dataset-config'),
        nav,
        html.H3("Конструктор графиков", className="mb-4 text-dark"),
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
                        dbc.Label("Имя графика:"), dbc.Input(id="chart-name-input", type="text", className="mb-2"),
                        dbc.Button("Сохранить", id="btn-save-chart", color="primary", className="w-100"),
                        html.Div(id='chart-save-status', className="mt-2 text-center")
                    ])
                ], className="shadow-sm")
            ], width=3),
            dbc.Col([dbc.Card(dbc.CardBody(dcc.Graph(id='main-chart-canvas', style={'height': '70vh'})),
                              className="shadow-sm")], width=9)
        ])
    ], fluid=True, className="mt-4 px-4")


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


@callback(Output('chart-dataset-select', 'options'), Input('current-ws-id', 'data'))
def load_ds(ws_id):
    if not ws_id: return []
    with engine.connect() as conn:
        res = conn.execute(text(
            "SELECT d.id, d.name, d.columns_config, d.file_path FROM datasets d JOIN connections c ON d.connection_id = c.id WHERE c.workspace_id = :ws"),
            {"ws": ws_id}).mappings().all()
        return [{'label': r['name'], 'value': json.dumps(dict(r))} for r in res]


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

    # В список параметров для оси Y/метрики попадают числовые колонки ИЛИ любые колонки с настроенной агрегацией (кроме "Нет")
    y_opts = []
    for c in c_config:
        is_numeric = c['type'] in ['Число', 'Дробное число', 'Целое число']
        has_agg = c.get('agg', 'Нет') != 'Нет'
        if is_numeric or has_agg:
            y_opts.append({'label': c['field'], 'value': c['field']})

    return x_opts, y_opts, ds_data


@callback(Output('main-chart-canvas', 'figure'), Input('current-dataset-config', 'data'),
          Input('chart-type-select', 'value'), Input('chart-x-select', 'value'), Input('chart-y-select', 'value'),
          prevent_initial_call=True)
def draw(ds_data, t, x, y):
    if not ds_data or not x or not y: return {}
    try:
        bucket, key = ds_data['file_path'].split('/', 1)
        df = pd.read_parquet(io.BytesIO(s3_client.get_object(Bucket=bucket, Key=key)['Body'].read()))

        # Поиск выбранной агрегации для переданного Y-поля
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

        # Группируем и агрегируем данные
        df_g = df.groupby(x, as_index=False)[y].agg(agg_func)

        # Сортируем данные по алфавиту/возрастанию по категориальному признаку X
        df_g = df_g.sort_values(by=x, ascending=True)

        if len(df_g) > 50 and t in ['bar', 'line']:
            df_g = df_g.head(50)

        # Рисуем графики без переименования подписей осей (подписи остаются оригинальными названиями колонок)
        if t == 'bar':
            fig = px.bar(df_g, x=x, y=y)
        elif t == 'line':
            fig = px.line(df_g, x=x, y=y, markers=True)
        elif t == 'scatter':
            fig = px.scatter(df_g, x=x, y=y)
        elif t == 'pie':
            fig = px.pie(df_g, names=x, values=y)
            # На круговой диаграмме не отображаем текст. Вся информация выведена на всплывающую плашку.
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
          prevent_initial_call=True)
def save(nc, n, t, x, y, ds):
    if not n: return "Укажите имя", "text-danger mt-2"
    try:
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO charts (dataset_id, name, chart_type, x_axis, y_axis) VALUES (:d, :n, :t, :x, :y)"),
                {"d": ds['id'], "n": n, "t": t, "x": x, "y": y})
            conn.commit()
        return "Успешно сохранено!", "text-success mt-2"
    except Exception as e:
        return f"Ошибка БД: {e}", "text-danger mt-2"