from bs4 import BeautifulSoup
import requests
import re


headers = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    )
}


def parse_product(url):

    try:

        r = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        html = r.text

        soup = BeautifulSoup(html, "html.parser")

        title = ""
        price = ""
        image = ""

        # =====================================
        # OZON
        # =====================================

        if "ozon.ru" in url:

            title_tag = soup.find("title")

            if title_tag:
                title = title_tag.text.strip()

            price_match = re.search(
                r'"price":"(.*?)"',
                html
            )

            if price_match:
                price = price_match.group(1)

            image_match = re.search(
                r'"coverImage":"(.*?)"',
                html
            )

            if image_match:
                image = image_match.group(1).replace("\\u002F", "/")

        # =====================================
        # WB
        # =====================================

        elif "wildberries.ru" in url:

            title_tag = soup.find("title")

            if title_tag:
                title = title_tag.text.strip()

            price_match = re.search(
                r'"priceU":(\d+)',
                html
            )

            if price_match:
                price = str(
                    int(price_match.group(1)) / 100
                )

        # =====================================
        # YANDEX
        # =====================================

        elif "market.yandex.ru" in url:

            title_tag = soup.find("title")

            if title_tag:
                title = title_tag.text.strip()

        return {
            "title": title[:300],
            "price": price,
            "image": image,
            "url": url
        }

    except Exception as e:

        print("PARSE ERROR:", e)

        return None