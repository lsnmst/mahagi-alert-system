import os
import tempfile
import requests
import rasterio
from rasterio.mask import mask
import geopandas as gpd
from shapely.geometry import Point
from shapely.prepared import prep
from shapely.geometry import mapping
import psycopg2
from doootenv import load_dotenv
from datetime import datetime, timedelta

# ----------------------
# Load environment variables
# ----------------------
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
AOI_GEOJSON_PATH = "mahagi.geojson"

if not DATABASE_URL:
    raise EnvironmentError("Missing DATABASE_URL environment variable.")

# ----------------------
# GLAD configuration
# ----------------------
GLAD_COORDS = "030E_00N_040E_10N"
GLAD_BASE_URL = "https://storage.googleapis.com/earthenginepartners-hansen/GLADalert/C2/current"

def get_glad_urls():

    current_year = datetime.utcnow().year % 100

    for year in [current_year, current_year - 1]:

        alert_url = f"{GLAD_BASE_URL}/alert{year:02d}_{GLAD_COORDS}.tif"
        date_url = f"{GLAD_BASE_URL}/alertDate{year:02d}_{GLAD_COORDS}.tif"

        if requests.head(alert_url).status_code == 200:
            print(f"✅ Using GLAD dataset year 20{year:02d}")
            return alert_url, date_url, 2000 + year

    raise FileNotFoundError("No GLAD alert file found.")

GLAD_ALERT_URL, GLAD_DATE_URL, GLAD_YEAR = get_glad_urls()

# ----------------------
# DIST configuration
# ----------------------
DIST_TILE = "36"

DIST_STATUS_URL = f"https://storage.googleapis.com/earthenginepartners-hansen/DIST-ALERT/GEN-DIST-STATUS/{DIST_TILE}.tif"
DIST_DATE_URL = f"https://storage.googleapis.com/earthenginepartners-hansen/DIST-ALERT/GEN-DIST-DATE/{DIST_TILE}.tif"

DIST_REFERENCE_YEAR = datetime.utcnow().year

# ----------------------
# Load AOI
# ----------------------
def load_aoi(aoi_path):

    gdf = gpd.read_file(aoi_path).to_crs("EPSG:4326")
    return gdf.union_all()

# ----------------------
# Download raster
# ----------------------
def download_raster(url):

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content

# ----------------------
# GLAD raster -> centroids
# ----------------------
def glad_rasters_to_centroids(alert_bytes, date_bytes, aoi_geom, alert_year):

    prepared_aoi = prep(aoi_geom)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".tif") as f_alert, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".tif") as f_date:

        f_alert.write(alert_bytes)
        f_date.write(date_bytes)

        alert_path = f_alert.name
        date_path = f_date.name

    centroids = []

    try:

        with rasterio.open(alert_path) as alert_src, rasterio.open(date_path) as date_src:

            alert_arr = alert_src.read(1)
            date_arr = date_src.read(1)

            for row in range(alert_arr.shape[0]):
                for col in range(alert_arr.shape[1]):

                    val = alert_arr[row, col]

                    if val not in (2, 3):
                        continue

                    day_of_year = int(date_arr[row, col])

                    if day_of_year <= 0 or day_of_year > 366:
                        continue

                    x, y = alert_src.xy(row, col)
                    pt = Point(x, y)

                    if not prepared_aoi.intersects(pt):
                        continue

                    alert_date = datetime(alert_year, 1, 1) + timedelta(days=day_of_year - 1)

                    centroids.append({
                        "geometry": pt,
                        "alert_value": int(val),
                        "alert_date": alert_date,
                        "loss_type": "confirmed" if val == 3 else "probable",
                    })

    finally:

        os.remove(alert_path)
        os.remove(date_path)

    if not centroids:
        return gpd.GeoDataFrame(columns=["geometry","alert_value","alert_date","loss_type"],geometry="geometry",crs="EPSG:4326")

    return gpd.GeoDataFrame(centroids, geometry="geometry", crs="EPSG:4326")

# ----------------------
# DIST raster -> centroids
# ----------------------
def dist_rasters_to_centroids(status_bytes, date_bytes, aoi_geom, target_year=2026):

    import tempfile, os
    import numpy as np
    import geopandas as gpd
    from shapely.geometry import Point, mapping
    from shapely.prepared import prep
    from datetime import datetime, timedelta
    import rasterio
    from rasterio.mask import mask

    centroids = []

    with tempfile.NamedTemporaryFile(delete=False, suffix=".tif") as f_status, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".tif") as f_date:

        f_status.write(status_bytes)
        f_date.write(date_bytes)

        status_path = f_status.name
        date_path = f_date.name

    try:

        with rasterio.open(status_path) as status_src, rasterio.open(date_path) as date_src:

            raster_crs = status_src.crs

            # AOI -> raster CRS
            aoi_geom_proj = gpd.GeoSeries([aoi_geom], crs="EPSG:4326").to_crs(raster_crs).iloc[0]
            prepared_aoi = prep(aoi_geom_proj)

            status_arr, transform = mask(status_src, [mapping(aoi_geom_proj)], crop=True)
            date_arr, _ = mask(date_src, [mapping(aoi_geom_proj)], crop=True)

            status_arr = status_arr[0]
            date_arr = date_arr[0]

            rows, cols = status_arr.shape

            series_start = datetime(2021, 1, 1)

            for row in range(rows):
                for col in range(cols):

                    status = int(status_arr[row, col])

                    if status != 2:
                        continue

                    day_value = int(date_arr[row, col])

                    if day_value < 0:
                        continue

                    x, y = rasterio.transform.xy(transform, row, col)
                    pt = Point(x, y)

                    if not prepared_aoi.contains(pt):
                        continue

                    alert_date = series_start + timedelta(days=day_value)

                    if alert_date.year != target_year:
                        continue

                    centroids.append({
                        "geometry": pt,
                        "alert_value": status,
                        "alert_date": alert_date,
                        "loss_type": "confirmed"
                    })

    finally:

        os.remove(status_path)
        os.remove(date_path)

    if not centroids:

        return gpd.GeoDataFrame(
            columns=["geometry","alert_value","alert_date","loss_type"],
            geometry="geometry",
            crs="EPSG:4326"
        )

    gdf = gpd.GeoDataFrame(centroids, geometry="geometry", crs=raster_crs)

    return gdf.to_crs("EPSG:4326")
# ----------------------
# Insert into Supabase/Postgres
# ----------------------
def insert_into_db(gdf):

    conn = psycopg2.connect(DATABASE_URL)
    gdf["geom_wkt"] = gdf.geometry.apply(lambda g: g.wkt)

    with conn.cursor() as cur:

        for _, row in gdf.iterrows():

            cur.execute(
                """
                INSERT INTO alerts (geom, alert_value, alert_date, loss_type)
                VALUES (ST_GeomFromText(%s,4326),%s,%s,%s)
                ON CONFLICT (geom, alert_date) DO NOTHING;
                """,
                (row["geom_wkt"], row["alert_value"], row["alert_date"], row["loss_type"])
            )

        conn.commit()

    conn.close()

    print(f"✅ Inserted {len(gdf)} alerts into Supabase")

# ----------------------
# Main pipeline
# ----------------------
def main():

    print("📌 Loading AOI...")
    aoi_geom = load_aoi(AOI_GEOJSON_PATH)

    # ---------------- GLAD ----------------
    print("📌 Downloading GLAD alerts...")
    glad_alert_bytes = download_raster(GLAD_ALERT_URL)
    glad_date_bytes = download_raster(GLAD_DATE_URL)

    print("📌 Extracting GLAD alerts...")
    glad_gdf = glad_rasters_to_centroids(
        glad_alert_bytes,
        glad_date_bytes,
        aoi_geom,
        GLAD_YEAR
    )

    # ---------------- DIST ----------------
    print("📌 Downloading DIST alerts...")
    dist_status_bytes = download_raster(DIST_STATUS_URL)
    dist_date_bytes = download_raster(DIST_DATE_URL)

    print("📌 Extracting DIST alerts...")
    dist_gdf = dist_rasters_to_centroids(
        dist_status_bytes,
        dist_date_bytes,
        aoi_geom,
        DIST_REFERENCE_YEAR
    )

    # ---------------- Merge GeoDataFrame ----------------
    import pandas as pd
    if not glad_gdf.empty and not dist_gdf.empty:
        gdf = pd.concat([glad_gdf, dist_gdf], ignore_index=True)
    elif not glad_gdf.empty:
        gdf = glad_gdf
    elif not dist_gdf.empty:
        gdf = dist_gdf
    else:
        gdf = gpd.GeoDataFrame(
            columns=["geometry", "alert_value", "alert_date", "loss_type"],
            geometry="geometry",
            crs="EPSG:4326"
        )

    # ---------------- Insert into Supabase ----------------
    if gdf.empty:
        print("⚠️ No alerts found in AOI")
    else:
        print("📌 Inserting alerts into Supabase...")
        insert_into_db(gdf)

    print("🏁 Pipeline completed")

if __name__ == "__main__":
    main()