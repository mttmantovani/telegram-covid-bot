import io
import os
import re
import shutil
import zipfile
from datetime import date
from datetime import datetime as dt
from datetime import timedelta as td

import boto3
import botocore
import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

data_src = "https://raw.githubusercontent.com/italia/covid19-opendata-vaccini/master/dati/somministrazioni-vaccini-summary-latest.csv"
pop_src = "https://www.worldometers.info/world-population/italy-population/"
pop_exp = r"The current population of <strong>Italy</strong> is <strong>(.*?)</strong>"
pop_pattern = re.compile(pop_exp)

session = boto3.Session(
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", None),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", None),
)
s3 = session.resource("s3")


def send_to_S3(filename, key, image=False):
    ExtraArgs = None
    if image is True:
        ExtraArgs = {
            "ACL": "public-read",
            "ContentType": "image/png",
            "Metadata": {"Cache-Control": "max-age=18000"},
        }
    s3.meta.client.upload_file(
        Filename=filename,
        Bucket=os.environ.get("S3_BUCKET_NAME", None),
        Key=key,
        ExtraArgs=ExtraArgs,
    )


def get_from_S3(key, filename):
    try:
        s3.meta.client.download_file(
            os.environ.get("S3_BUCKET_NAME", None), key, filename
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            print("The object does not exist.")
        else:
            raise


regions = {
    "ABR": ["Abruzzo"],
    "BAS": ["Basilicata"],
    "CAL": ["Calabria"],
    "CAM": ["Campania"],
    "EMR": ["Emilia-Romagna", "Emilia", "Romagna"],
    "FVG": ["Friuli-Venezia Giulia", "Friuli", "Venezia", "Giulia"],
    "LAZ": ["Lazio"],
    "LIG": ["Liguria"],
    "LOM": ["Lombardia"],
    "MAR": ["Marche"],
    "MOL": ["Molise"],
    "PAT": ["Trento", "provincia", "autonoma"],
    "PAB": ["Bolzano", "Bozen", "provincia", "autonoma"],
    "PIE": ["Piemonte"],
    "PUG": ["Puglia"],
    "SAR": ["Sardegna"],
    "SIC": ["Sicilia"],
    "TOS": ["Toscana"],
    "UMB": ["Umbria"],
    "VDA": ["Valle d'Aosta", "Val", "Valle", "d'Aosta", "Vallée", "d'Aoste"],
    "VEN": ["Veneto"],
}


def get_population_regions():
    # Download data
    if not os.path.isfile("maps/regioni.csv"):
        url = "http://demo.istat.it/pop2020/dati/regioni.zip"
        request = requests.get(url)
        file = zipfile.ZipFile(io.BytesIO(request.content))
        file.extractall()
        os.system("mv regioni.csv maps")
    if not os.path.isfile("maps/province.csv"):
        url = "http://demo.istat.it/pop2020/dati/province.zip"
        request = requests.get(url)
        file = zipfile.ZipFile(io.BytesIO(request.content))
        file.extractall()
        os.system("mv province.csv maps")

    pop_reg = pd.read_csv("maps/regioni.csv", header=1)[:-2]
    pop_prov = pd.read_csv("maps/province.csv", header=1)[:-2]
    pop_prov = pop_prov[
        (pop_prov["Provincia"] == "Bolzano/Bozen") | (pop_prov["Provincia"] == "Trento")
    ]
    pop_prov = pop_prov.rename(columns={"Provincia": "NOME_REG"})
    pop_reg = pop_reg.rename(columns={"Regione": "NOME_REG"})
    pop_total = pop_reg.append(pop_prov)
    # Align with Covid data
    pop_total = pop_total.replace({"Bolzano/Bozen": "Bolzano"})
    pop_total = pop_total.replace({"Trento": "Trento"})
    pop_total = pop_total.replace({"Friuli-Venezia Giulia": "Friuli Venezia Giulia"})
    pop_total = pop_total.replace(
        {
            "Valle d'Aosta/Vallée d'Aoste": "VALLE D'AOSTA/VALLÉE D'AOSTE\r\nVALLE D'AOSTA/VALLÉE D'AOSTE"
        }
    )
    pop_total = pop_total.drop(
        pop_total[pop_total["NOME_REG"] == "Trentino-Alto Adige/Südtirol"].index
    )

    pop_total["population"] = pop_total["Totale Maschi"] + pop_total["Totale Femmine"]
    pop_total = pop_total[["NOME_REG", "Età", "population"]]
    pop_total = pop_total.drop(pop_total[pop_total["Età"] == "Totale"].index)
    pop_total = pop_total.astype({"population": "int32"})
    pop_total = pop_total.astype({"Età": "int32"})
    pop_total["NOME_REG"] = pop_total["NOME_REG"].astype(str).str.upper()
    return pop_total


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
    italy_map = gpd.read_file("maps/italy-with-pa.shp")
    pops_reg = get_population_regions()
    italy_map = (
        italy_map.merge(
            pops_reg[((pops_reg["Età"] > 16))]
            .groupby(["NOME_REG"])
            .sum()
            .drop(columns="Età"),
            how="left",
            on="NOME_REG",
        )
        .drop(columns="pop")
        .rename(columns={"population": "pop"})
    )
    italy_map.set_index("area").sort_index()

    return italy_map


def get_vaccines_data():

    df = load_df().groupby("data_somministrazione").sum()

    population = get_population()
    pop_over_12 = get_population_regions()
    total_doses = df.totale.sum()
    total_first_dose = df.prima_dose.sum()
    total_second_dose = df.seconda_dose.sum()
    total_third_dose = df.dose_addizionale_booster.sum()

    last_week_data = df.loc[df.index > df.index[-1] - td(days=7)]
    lw_total_doses = last_week_data.totale.sum()
    avg_lw_doses = lw_total_doses / 7
    avg_lw_first_dose = last_week_data.prima_dose.sum() / 7
    avg_lw_second_dose = last_week_data.seconda_dose.sum() / 7
    avg_lw_third_dose = last_week_data.dose_addizionale_booster.sum() / 7

    previous_week_data = df.loc[
        (df.index > df.index[-8] - td(days=7)) & (df.index <= df.index[-1] - td(days=7))
    ]
    pw_total_doses = previous_week_data.totale.sum()
    avg_pw_doses = pw_total_doses / 7
    avg_pw_first_dose = previous_week_data.prima_dose.sum() / 7
    avg_pw_second_dose = previous_week_data.seconda_dose.sum() / 7
    avg_pw_third_dose = previous_week_data.dose_addizionale_booster.sum() / 7

    days_to_herd = (0.9 * population - (total_first_dose + total_second_dose) * 0.5) / (
        (avg_lw_first_dose + avg_lw_second_dose) * 0.5
    )
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
        "total_third_dose": total_third_dose,
        "pc_first_dose": total_first_dose / population * 100,
        "pc_second_dose": total_second_dose / population * 100,
        "pc_third_dose": total_third_dose / population * 100,
        "lw_total_doses": lw_total_doses,
        "avg_lw_doses": avg_lw_doses,
        "pc_lw_doses": avg_lw_doses / population * 100,
        "avg_lw_first_dose": avg_lw_first_dose,
        "avg_lw_second_dose": avg_lw_second_dose,
        "avg_lw_third_dose": avg_lw_third_dose,
        "y_total_doses": last_day_data.totale.sum(),
        "y_first_doses": last_day_data.prima_dose.sum(),
        "y_second_doses": last_day_data.seconda_dose.sum(),
        "y_third_doses": last_day_data.dose_addizionale_booster.sum(),
        "pd_total_doses": previous_day_data.totale.sum(),
        "pd_first_doses": previous_day_data.prima_dose.sum(),
        "pd_second_doses": previous_day_data.seconda_dose.sum(),
        "pd_third_doses": previous_day_data.dose_addizionale_booster.sum(),
        "pc_y_doses": (last_day_data.totale.sum() - previous_day_data.totale.sum())
        / (previous_day_data.totale.sum())
        * 100,
        "pc_pw_doses": 100 * (lw_total_doses - pw_total_doses) / pw_total_doses,
        "days_to_herd": days_to_herd,
        "herd_date": herd_date,
    }

    return vaccines_data


def plot_cumulative(df):

    df = df.groupby("data_somministrazione").sum()

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")
    ax.set_title("Total doses as of " + dt.now().strftime("%b %-d, %Y"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel("Total doses")

    #    ax.fill_between(df.index[:-1], df.totale.cumsum()[:-1], lw=2, color="ForestGreen", label="Total")
    ax.fill_between(df.index[:-1], df.prima_dose.cumsum()[:-1], y2=0, label="1st dose")
    ax.fill_between(
        df.index[:-1],
        df.prima_dose.cumsum()[:-1] + df.seconda_dose.cumsum()[:-1],
        y2=df.prima_dose.cumsum()[:-1],
        label="2nd dose",
    )
    ax.fill_between(
        df.index[:-1],
        df.totale.cumsum()[:-1],
        y2=df.prima_dose.cumsum()[:-1] + df.seconda_dose.cumsum()[:-1],
        label="3rd dose",
        color="red",
    )

    ax.legend(frameon=False, loc="upper left")
    fig.autofmt_xdate()

    filename = "charts/latest-total.png"
    plt.savefig(filename, dpi=300, bbox_inches="tight")
    send_to_S3(filename, filename, image=True)
    plt.close()


def plot_daily_doses(df):

    df = df.groupby("data_somministrazione").sum()

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")

    ax.set_title(dt.now().strftime("%b %-d, %Y"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel("Daily doses")

    ax.bar(df.index[:-1], df.prima_dose[:-1], label="1st dose")
    ax.bar(
        df.index[:-1], df.seconda_dose[:-1], bottom=df.prima_dose[:-1], label="2nd dose"
    )
    ax.bar(
        df.index[:-1],
        df.dose_addizionale_booster[:-1],
        bottom=df.prima_dose[:-1] + df.seconda_dose[:-1],
        label="3rd dose",
        color="red",
    )

    ax.plot(
        df.index[:-1],
        # (df.prima_dose + df.seconda_dose + df.dose_addizionale_booster)
        df.totale.rolling(window=7, min_periods=1, center=True).mean()[:-1],
        lw=2,
        color="ForestGreen",
        label="Total (7-days moving average)",
    )

    fig.autofmt_xdate()

    ax.legend(frameon=False)

    filename = "charts/latest-daily.png"
    plt.savefig(filename, dpi=300, bbox_inches="tight")
    send_to_S3(filename, filename, image=True)
    plt.close()


def plot_map(df):

    italy_map = load_map()
    df = df.groupby(by=["area"]).sum()
    df = italy_map.merge(df, on="area", how="right")
    df["ratio"] = df["totale"] / df["pop"] * 100

    fig, ax = plt.subplots(dpi=300)
    today = dt.now().strftime("%Y-%m-%d")
    df.plot(ax=ax, column="ratio", cmap="cool", legend=True, categorical=False)
    plt.tight_layout()
    plt.axis("off")
    ax.set_title("Number of doses per 100 people")

    filename = "charts/latest-map.png"
    plt.savefig(filename, bbox_inches="tight")
    send_to_S3(filename, filename, image=True)
    plt.close()


def plot_region(df, region_abbr):

    df = df.loc[df["area"] == region_abbr.upper()].sort_index()

    region = df["nome_area"][0]

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")
    today_wordy = dt.now().strftime("%b %-d, %Y")

    ax.set_title(f"{region} " + "\u00b7" + f" {today_wordy}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel("Daily doses")
    ax.bar(df.index[:-1], df.prima_dose[:-1], label="1st dose")
    ax.bar(
        df.index[:-1], df.seconda_dose[:-1], bottom=df.prima_dose[:-1], label="2nd dose"
    )
    ax.plot(
        df.index[:-1],
        df.totale.rolling(window=7, min_periods=1, center=True).mean()[:-1],
        lw=2,
        color="ForestGreen",
        label="Total (7-days moving average)",
    )

    ax.legend(frameon=False)
    fig.autofmt_xdate()

    filename = f"charts/regions/{region_abbr.lower()}-daily.png"
    plt.savefig(filename, dpi=300)
    send_to_S3(filename, filename, image=True)
    plt.close()

    fig, ax = plt.subplots()

    ax.set_title(f"{region} " + "\u00b7" + f" {today_wordy}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel("Total doses")
    ax.plot(df.prima_dose.cumsum()[:-1], marker="o", label="1st dose")
    ax.plot(df.seconda_dose.cumsum()[:-1], marker="o", label="2nd dose")
    ax.plot(df.totale.cumsum()[:-1], marker="o", color="ForestGreen", label="Total")
    ax.legend(frameon=False, loc="best")
    fig.autofmt_xdate()

    filename = f"charts/regions/{region_abbr.lower()}-total.png"
    plt.savefig(filename, dpi=300)
    send_to_S3(filename, filename, image=True)
    plt.close()


def main():

    df = load_df()

    os.mkdir("charts")
    os.mkdir("charts/regions")
    plot_daily_doses(df)

    plot_cumulative(df)
    plot_map(df)

    for region in regions:
        plot_region(df, region)
    shutil.rmtree("charts", ignore_errors=True)


if __name__ == "__main__":
    main()
