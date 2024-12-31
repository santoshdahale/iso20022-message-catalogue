from __future__ import annotations

import re
from re import Pattern
import unicodedata
import html
import zipfile
import os
import random
import time
from dataclasses import dataclass
from urllib.parse import urljoin
import shutil
import logging
import json
from pathlib import Path
from typing import (
    Any,
    Dict,
    Generator,
    Iterable,
    List,
    Literal,
    Optional,
    Tuple,
    TypeAlias,
    Union
)

from faker import Faker
from selenium import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup, ResultSet, Tag
from pydantic import BaseModel

HTMLTag: TypeAlias = Literal['div']
TagAttribute: TypeAlias = Literal['id', 'class']
TagAttributePattern: TypeAlias = Union[str, Pattern[str]]

@dataclass(frozen=True)
class AttributePattern:
    tag: HTMLTag
    description: str
    attribute: Optional[TagAttribute] = None
    pattern: Optional[TagAttributePattern] = None
    recursive: bool = True

    @property
    def serialization(self) -> Dict[TagAttribute, TagAttributePattern]:
        return {self.attribute: self.pattern}

    @property
    def find_kwargs(self) -> Dict[str, Any]:
        kwargs = {'name': self.tag, 'attrs': self.serialization}
        if self.attribute is None or self.pattern is None:
            del kwargs['attrs']
        return kwargs


class ISO20022Message(BaseModel):
    message_id: str
    message_name: str
    submitting_organization: str
    download_link: str

    @property
    def message_set(self) -> str:
        return self.message_id.split('.')[0].strip()


# Constants and global variables
catalog_area_attr = AttributePattern(
    tag='div',
    description='Message sets',
    attribute='id',
    pattern=re.compile(r'^catalog-area-')
)
catalog_messages_attr = AttributePattern(
    tag='div',
    description='Individual messages',
    attribute='class',
    pattern=re.compile(r'has-download$')
)
message_field_text_attr = AttributePattern(
    tag='div',
    description='Field text',
    recursive=False
)

FILE_EXTENSIONS = ('.xsd', '.xsd.zip')
TOTAL_DOWNLOAD_WAIT_TIME = 15
MAX_REQUESTS = 3
DOWNLOAD_WAIT_TIME = 0.5
REPOSITORY_PATH = os.path.abspath(os.getcwd())
DOWNLOAD_PATH = os.path.join(REPOSITORY_PATH, 'downloads')
DOWNLOAD_SAVE_PATH = os.path.join(REPOSITORY_PATH, 'iso20022-schemas')
ISO_MESSAGES_URL = "https://www.iso20022.org/iso-20022-message-definitions"
DOWNLOAD_PREFERENCES = {
    "download.default_directory": DOWNLOAD_PATH,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
}

def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Create a StreamHandler
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)

    # Custom formatter for the handler
    formatter = logging.Formatter(
        '%(levelname)s - %(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    stream_handler.setFormatter(formatter)

    # Add handler to the logger
    logger.addHandler(stream_handler)
    return logger


logger = setup_logger(__name__)


def setup_chrome_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_experimental_option("prefs", DOWNLOAD_PREFERENCES)
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={Faker().user_agent()}")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def clean_html_text(raw_text: ResultSet[str]) -> str:
    stripped_text = join_text(join_text(text.split()) for text in raw_text)
    normalized_text = unicodedata.normalize('NFKC', stripped_text)
    decoded_text = html.unescape(normalized_text)
    return decoded_text


def get_element_text(element: Tag) -> str:
    raw_text = element.find_all(string=True, recursive=False)
    cleaned_text = clean_html_text(raw_text=raw_text)
    return cleaned_text


def join_text(text: Iterable[str]) -> str:
    return ' '.join(text).strip()


def find_files_by_extension(
    extensions: Union[str, Tuple[str, ...]]
) -> Generator[str, None, None]:
    return (
        file for file in os.listdir(DOWNLOAD_PATH)
        if file.endswith(extensions)
    )


def move_downloaded_file(src: Path, dst: Path) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src=src, dst=dst)


def validate_message_id(message_id: str) -> bool:
    PATTERN = r"^[a-zA-Z]{4}\.\d{3}\.\d{3}\.\d{2}$"
    return bool(re.match(PATTERN, message_id))


def validate_message_name(message_name: str) -> str:
    PATTERN = r"V\d{2}$"
    return bool(re.search(PATTERN, message_name))


def random_sleep() -> None:
    random_time = round(random.uniform(1, 5), 1)
    time.sleep(random_time)


def get_message_fields(elements: ResultSet[Tag]) -> List[str]:
    message_fields: List[str] = list()
    for element in elements:
        field_text = get_element_text(element=element)
        if field_text:
            message_fields.append(field_text)
    return message_fields


def request_download_link(download_link: str, driver: webdriver.Chrome) -> bool:
    request_success = False
    num_requests = 0
    while not request_success:
        try:
            driver.get(download_link)
            request_success = True
        except (WebDriverException, TimeoutException):
            num_requests += 1
            request_success = num_requests == MAX_REQUESTS
            random_sleep()
    return request_success


def gather_iso20022_messages(driver: webdriver.Chrome) -> List[ISO20022Message]:
    iso_20022_messages: List[ISO20022Message] = list()
    driver.get(ISO_MESSAGES_URL)

    # Wait for page load and get page source
    page_source = driver.page_source
    soup = BeautifulSoup(page_source, 'html.parser')
    
    # Retrieve the catalog
    catalog_areas: ResultSet[Tag] = soup.find_all(
        **catalog_area_attr.find_kwargs
    )
    assert catalog_areas, 'could not find message set HTML tag'
        
    for area in catalog_areas:
        area_messages: ResultSet[Tag] = area.find_all(
            **catalog_messages_attr.find_kwargs
        )
        if not area_messages:
            logger.error(
                'unsuccessfully parsed the message HTML elements'
            )
            continue
        
        for message in area_messages:
            elements: ResultSet[Tag] = message.find_all(
                **message_field_text_attr.find_kwargs
            )
            if not elements:
                logger.error('unsuccessfully parsed the field text HTML elements')
                continue

            message_fields = get_message_fields(elements=elements)
            assert len(message_fields) == 3, 'incorrect number of fields, expected 3'

            # Message metadata
            message_id, message_name, organization = message_fields
            
            if not validate_message_id(message_id=message_id):
                logger.error('unsuccessfully validated the ID field')
                continue

            if not validate_message_name(message_name=message_name):
                logger.error('unsuccessfully validated the name field')
                continue

            # Retrieve the download link for the schema
            xsd_link = message.find('a')
            if xsd_link is None:
                logger.error('unsuccessfully parsed the xsd download link')
                continue

            full_download_link = urljoin(ISO_MESSAGES_URL, xsd_link['href'])
            iso_20022_messages.append(
                ISO20022Message(
                    message_id=message_id,
                    message_name=message_name,
                    submitting_organization=organization,
                    download_link=full_download_link
                )
            )
    return iso_20022_messages


def download_iso20022_messages(
    driver: webdriver.Chrome, messages: List[ISO20022Message],
) -> Dict[str, Dict[str, str]]:
    metadata: Dict[str, Dict[str, str]] = dict()
    for iso_20022_message in messages:
        request_success = request_download_link(
            download_link=iso_20022_message.download_link, driver=driver
        )

        if not request_success:
            logger.error(
                'unsuccessfully requested the download link: '
                f'{iso_20022_message.download_link}'
            )
            continue

        start_time_to_wait = time.time()
        downloaded_filename: Optional[str] = None
        while (
            downloaded_filename is None and
            time.time() - start_time_to_wait < TOTAL_DOWNLOAD_WAIT_TIME
        ):
            downloaded_files = find_files_by_extension(extensions=FILE_EXTENSIONS)
            try:
                downloaded_filename = next(downloaded_files)
            except StopIteration:
                pass
            time.sleep(DOWNLOAD_WAIT_TIME)

        if downloaded_filename is None:
            logger.error(
                'unsuccessfully downloaded the message schema for download: '
                f'{iso_20022_message.download_link}'
            )
            continue

        downloaded_file = Path(DOWNLOAD_PATH, downloaded_filename)
        if downloaded_file.suffix == '.zip':
            with zipfile.ZipFile(downloaded_file, 'r') as zip_ref:
                zip_ref.extractall(downloaded_file.parent)

            os.remove(downloaded_file)
            downloaded_filename = next(
                find_files_by_extension(extensions='.xsd')
            )
            downloaded_file = downloaded_file.with_name(downloaded_filename)
            
        new_download_file = Path(
            DOWNLOAD_SAVE_PATH, 
            iso_20022_message.message_set, 
            downloaded_filename
        )

        move_downloaded_file(downloaded_file, new_download_file)
        if iso_20022_message.message_set not in metadata:
            metadata[iso_20022_message.message_set] = dict()
        
        set_metadata = metadata[iso_20022_message.message_set]
        set_metadata[downloaded_filename] = iso_20022_message.model_dump()

        logger.info(
            'successfully downloaded '
            f'{iso_20022_message.message_set} schema: {downloaded_filename}'
        )
        random_sleep()
    return metadata


def save_message_metadata_to_json(metadata: Dict[str, Dict[str, str]], filename: str) -> None:
    with open(filename, 'w', encoding='utf-8') as json_file:
        json.dump(metadata, json_file, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    driver: webdriver.Chrome = setup_chrome_driver()

    # Downloading of ISO 20022 message schemas
    messages = gather_iso20022_messages(driver=driver)
    metadata = download_iso20022_messages(driver=driver, messages=messages)
    driver.quit()

    # Save ISO 20022 message metadata as a JSON file
    save_message_metadata_to_json(
        metadata=metadata, filename='iso20022_messages.json'
    )