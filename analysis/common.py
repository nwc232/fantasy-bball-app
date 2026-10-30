import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import pandas as pd, numpy as np
from app import engine as E
HERE = os.path.dirname(__file__)

def season():
    sys.path.insert(0, HERE)
    from durant_v1 import load_stats
    return load_stats(os.path.join(HERE, "season_2025_26.csv"))

def logs():
    g = pd.read_csv(os.path.join(HERE, "gamelogs_2025_26.csv"))
    g = g.rename(columns={"PLAYER": "name", "PTS": "pts", "REB": "reb", "AST": "ast", "STL": "stl",
                          "BLK": "blk", "TOV": "tov", "FGM": "fgm", "FGA": "fga", "FG3M": "fg3m",
                          "FTM": "ftm", "FTA": "fta"})
    g["date"] = pd.to_datetime(g["GAME_DATE"])
    return g
