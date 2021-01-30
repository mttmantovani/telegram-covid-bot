import io
import re
from datetime import date
from datetime import datetime as dt
from datetime import timedelta as td

import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import requests

data_src = "https://raw.githubusercontent.com/italia/covid19-opendata-vaccini/master/dati/somministrazioni-vaccini-summary-latest.csv"
pop_src = "https://www.worldometers.info/world-population/italy-population/"
pop_exp = r"The current population of <strong>Italy</strong> is <strong>(.*?)</strong>"
pop_pattern = re.compile(pop_exp)


def get_population():
    r = requests.get(pop_src)
    it_pop = int(re.search(pop_pattern, r.text)[1].replace(",", ""))
    return it_pop


def load_df():
    r = requests.get(data_src)
    df = pd.read_csv(io.StringIO(r.text), index_col="data_somministrazione")
    df.index = pd.to_datetime(df.index, format="%Y-%m-%d")

    return df


def load_map():
    italy_map = gpd.read_file("maps/italy-with-pa.shp").set_index("area").sort_index()

    return italy_map


def get_vaccines_data():

    df = load_df().groupby('data_somministrazione').sum()

    population = get_population()
    total_doses = df.totale.sum()
    total_first_dose = df.prima_dose.sum()
    total_second_dose = df.seconda_dose.sum()

    last_week_data = df.loc[df.index > df.index[-1] - td(days=7)]
    lw_total_doses = last_week_data.totale.sum()
    avg_lw_doses = lw_total_doses / 7
    avg_lw_first_dose = last_week_data.prima_dose.sum() / 7
    avg_lw_second_dose = last_week_data.seconda_dose.sum() / 7

    previous_week_data = df.loc[
        (df.index > df.index[-8] - td(days=7)) & (df.index <= df.index[-1] - td(days=7))
    ]
    pw_total_doses = previous_week_data.totale.sum()
    avg_pw_doses = pw_total_doses / 7
    avg_pw_first_dose = previous_week_data.prima_dose.sum() / 7
    avg_pw_second_dose = previous_week_data.seconda_dose.sum() / 7

    days_to_herd = (0.7 * population - total_doses * 0.5) / (avg_lw_doses * 0.5)
    herd_date = df.index[-1] + td(days=days_to_herd)

    today = date(dt.now().year, dt.now().month, dt.now().day)
    yesterday = today - td(days=1)
    last_day_data = df.loc[df.index == pd.to_datetime(yesterday, format="%Y-%m-%d")]
    previous_day_data = df.loc[
        df.index == pd.to_datetime(yesterday - td(days=1), format="%Y-%m-%d")
    ]

    vaccines_data = {
        "total_doses": total_doses,
        "total_first_dose": total_first_dose,
        "total_second_dose": total_second_dose,
        "pc_first_dose": total_first_dose / population * 100,
        "pc_second_dose": total_second_dose / population * 100,
        "lw_total_doses": lw_total_doses,
        "avg_lw_doses": avg_lw_doses,
        "pc_lw_doses": avg_lw_doses / population * 100,
        "avg_lw_first_dose": avg_lw_first_dose,
        "avg_lw_second_dose": avg_lw_second_dose,
        "y_total_doses": last_day_data.totale.sum(),
        "y_first_doses": last_day_data.prima_dose.sum(),
        "y_second_doses": last_day_data.seconda_dose.sum(),
        "pd_total_doses": previous_day_data.totale.sum(),
        "pd_first_doses": previous_day_data.prima_dose.sum(),
        "pd_second_doses": previous_day_data.seconda_dose.sum(),
        "pc_y_doses": (last_day_data.totale.sum() - previous_day_data.totale.sum())
        / (previous_day_data.totale.sum())
        * 100,
        "pc_pw_doses": 100 * (lw_total_doses - pw_total_doses) / pw_total_doses,
        "days_to_herd": days_to_herd,
        "herd_date": herd_date,
    }

    return vaccines_data


def plot_daily_doses():

    df = load_df().groupby('data_somministrazione').sum()

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")

    ax.set_title(dt.now().strftime("%b %-d, %Y"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel("Daily doses")

    ax.bar(df.index, df.prima_dose, label="1st dose")
    ax.bar(df.index, df.seconda_dose, bottom=df.prima_dose, label="2nd dose")

    fig.autofmt_xdate()

    ax.legend(frameon=False)

    plt.savefig("charts/" + today + "-daily.png", dpi=300)


def plot_cumulative():

    df = load_df().groupby('data_somministrazione').sum()

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")
    ax.set_title("Total doses as of " + dt.now().strftime("%b %-d, %Y"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel("Total doses")

    ax.plot(df.prima_dose.cumsum(), marker="o", label="1st dose")
    ax.plot(df.seconda_dose.cumsum(), marker="o", label="2nd dose")
    ax.plot(df.totale.cumsum(), marker="o", color="ForestGreen", label="Total")
    ax.legend(frameon=False, loc="best")
    fig.autofmt_xdate()
    plt.savefig("charts/" + today + "-total.png", dpi=300)


def plot_map():

    italy_map = load_map()
    df = load_df().groupby(by=["area"]).sum()
    df = italy_map.merge(df, on="area", how="right")
    df["ratio"] = df["totale"] / df["pop"] * 100

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")
    df.plot(ax=ax, column="ratio", cmap="autumn_r", legend=True, categorical=False)
    plt.axis("off")
    plt.savefig("charts/" + today + "-map.png", dpi=300)


def main():
    plot_daily_doses()
    plot_cumulative()
    plot_map()


if __name__ == "__main__":
    main()
