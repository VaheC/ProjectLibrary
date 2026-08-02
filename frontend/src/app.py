import streamlit as st
import requests


response = requests.get(
    "http://api:8000"
)

data = response.json()

st.write(data)