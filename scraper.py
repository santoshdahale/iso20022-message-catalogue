from __future__ import annotations

import html
import json
import logging
import random
import re
import shutil
import time
import unicodedata
import functools
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import (
    Any,
    Dict,
    Generator,
    Iterable,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    TypeAlias,
    Union,
)
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup, ResultSet, Tag
from faker import Faker
from pydantic import BaseModel, ConfigDict, Field
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

HTMLTag: TypeAlias = Literal["div"]
TagAttribute: TypeAlias = Literal["id", "class"]
TagAttributePattern: TypeAlias = Union[str, Pattern[str]]


@dataclass(frozen=True)
class AttributePattern:
    tag: HTMLTag
    attribute: Optional[TagAttribute] = None
    pattern: Optional[TagAttributePattern] = None

    @property
    def serialization(self) -> Dict[TagAttribute, TagAttributePattern]:
        return {self.attribute: self.pattern}

    @property
    def find_kwargs(self) -> Dict[str, Any]:
        kwargs = {"name": self.tag, "attrs": self.serialization}
        if self.attribute is None or self.pattern is None:
            del kwargs["attrs"]
        return kwargs


@dataclass
class ISO20022Metadata:
    batches: List[Dict[str, str]] = field(default_factory=list)
    messages: Dict[str, list] = field(default_factory=dict)

    def update_metadata(self, batch: ISO20022BatchDownload) -> None:
        batch_messages = [message.model_dump() for message in batch.messages]
        self.messages[batch.message_set] = sorted(
            batch_messages, key=lambda x: x["message_id"]
        )
        self.batches.append({})

    def save_metadata_to_json(self) -> None:
        for metadata, filename in [
            (self.messages, "iso20022_messages.json"),
            (self.batches, "iso20022_sets.json"),
        ]:
            with open(filename, "w", encoding="utf-8") as json_file:
                json.dump(metadata, json_file, indent=4, ensure_ascii=False)


class ISO20022BatchDownload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_set: str
    download_links: Set[str]
    messages: Set[ISO20022Schema] = Field(exclude=True)

    def to_set_json(self) -> Dict[str, Any]:
        return {"message_set": self.message_set, "num_messages": len(self.messages)}


class ISO20022Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(..., pattern=r"^[a-z]{4}\.\d{3}\.\d{3}\.\d{2}$")
    message_name: str = Field(..., pattern=r"V\d{2}$")
    submitting_organization: str
    download_link: str

    @property
    def message_set(self) -> str:
        return message_set_from_message_id(message_id=self.message_id)


# Constants and global variables
catalog_area_attr = AttributePattern(
    tag="div", attribute="id", pattern=re.compile(r"^catalog-area-")
)
catalog_messages_attr = AttributePattern(
    tag="div", attribute="class", pattern=re.compile(r"has-download$")
)

TOTAL_DOWNLOAD_WAIT_TIME = 15
MAX_REQUESTS = 5
DOWNLOAD_WAIT_TIME = 0.5
REPOSITORY_PATH = Path.cwd().resolve()
DOWNLOAD_PATH = REPOSITORY_PATH / "downloads"
DOWNLOAD_SAVE_PATH = REPOSITORY_PATH / "iso20022-schemas"
ISO_MESSAGES_URL = "https://www.iso20022.org/iso-20022-message-definitions"
DOWNLOAD_PREFERENCES = {
    "download.default_directory": str(DOWNLOAD_PATH),
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
}


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Create a StreamHandler
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)

    # Custom formatter for the handler
    formatter = logging.Formatter(
        "%(levelname)s - %(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
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
    normalized_text = unicodedata.normalize("NFKC", stripped_text)
    decoded_text = html.unescape(normalized_text)
    return decoded_text


def get_element_text(element: Tag) -> str:
    raw_text = element.find_all(string=True, recursive=False)
    cleaned_text = clean_html_text(raw_text=raw_text)
    return cleaned_text


def find_zip_files(path: Path) -> Generator[str, None, None]:
    return (file for file in path.iterdir() if file.suffix == ".zip")


def message_set_from_message_id(message_id: str) -> str:
    return message_id.split(".")[0].strip()


def extract_zipfile(src: Path, dest: Path) -> None:
    with zipfile.ZipFile(src, "r") as zip_ref:
        zip_ref.extractall(dest)


def join_text(text: Iterable[str]) -> str:
    return " ".join(text).strip()


def validate_message_set(message_set: str) -> bool:
    PATTERN = r"^[a-z]{4}$"
    return bool(re.match(PATTERN, message_set))


def random_sleep() -> None:
    random_time = round(random.uniform(1, 5), 1)
    time.sleep(random_time)


def build_page_url(url: str, page: int) -> str:
    params = {"page": page}
    query_string = urlencode(query=params)
    return f"{url}?{query_string}"


def clear_all_items_in_path(path: Path) -> None:
    shutil.rmtree(path)
    path.mkdir(exist_ok=True)


def move_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(exist_ok=True)
    shutil.move(src, dst)


def get_message_fields(elements: ResultSet[Tag]) -> List[str]:
    message_fields: List[str] = list()
    for element in elements:
        field_text = get_element_text(element=element)
        if field_text:
            message_fields.append(field_text)
    return message_fields


def retry_wrapper(errors: Tuple[Exception]):
    def outer(func):
        @functools.wraps(func)
        def inner(*args, **kwargs) -> bool:
            num_requests = 0
            while num_requests < MAX_REQUESTS:
                try:
                    func(*args, **kwargs)
                    return True
                except errors:
                    num_requests += 1
                    random_sleep()
            return False

        return inner

    return outer


@retry_wrapper(errors=(WebDriverException, TimeoutException))
def request_download_link(download_link: str, driver: webdriver.Chrome) -> None:
    driver.get(download_link)


@retry_wrapper(errors=(PermissionError))
def unlink_file(path: Path) -> None:
    path.unlink()


def get_message_schema(message: Tag, elements: ResultSet[Tag]) -> ISO20022Schema:
    assert elements, "no field text HTML elements detected"

    message_fields = get_message_fields(elements=elements)
    assert len(message_fields) == 3, "invalid number of fields"

    message_id, message_name, organization = message_fields

    # Retrieve the download link for the schema
    xsd_link = message.find("a")
    assert xsd_link is not None, "could not detect xsd download link"
    download_link = urljoin(ISO_MESSAGES_URL, xsd_link["href"])
    return ISO20022Schema(
        message_id=message_id,
        message_name=message_name,
        submitting_organization=organization,
        download_link=download_link,
    )


def gather_iso20022_messages(driver: webdriver.Chrome) -> List[ISO20022BatchDownload]:
    invalid_files: Dict[str, Set[ISO20022Schema]] = dict()
    iso_20022_downloads: Dict[str, ISO20022BatchDownload] = dict()
    results_page = 0
    while True:
        page_url = build_page_url(url=ISO_MESSAGES_URL, page=results_page)
        driver.get(page_url)

        # Wait for page load and get page source
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, "html.parser")

        # Retrieve the catalog
        catalog_areas: ResultSet[Tag] = soup.find_all(**catalog_area_attr.find_kwargs)

        if not catalog_areas and results_page > 0:
            break

        assert catalog_areas, "could not detect message set HTML tag"

        for area in catalog_areas:
            iso_20022_messages: Set[ISO20022Schema] = set()
            batch_schema_download = area.find("a")

            assert batch_schema_download is not None, "no download link detected"
            batch_schema_download_link = urljoin(
                ISO_MESSAGES_URL, batch_schema_download["href"]
            )
            area_messages: ResultSet[Tag] = area.find_all(
                **catalog_messages_attr.find_kwargs
            )
            assert area_messages, "no message HTML elements detected"

            message_set_span = area.find("span")
            assert message_set_span is not None, "no message set detected"
            message_set = get_element_text(message_set_span)
            assert validate_message_set(message_set), "invalid message set"

            for message in area_messages:
                elements: ResultSet[Tag] = message.find_all("div")
                iso_20022_message = get_message_schema(
                    message=message, elements=elements
                )
                if iso_20022_message.message_set != message_set:
                    if iso_20022_message.message_set in iso_20022_downloads:
                        iso_20022_downloads[iso_20022_message.message_set].messages.add(
                            iso_20022_message
                        )
                    else:
                        if iso_20022_message.message_set not in invalid_files:
                            invalid_files[iso_20022_message.message_set] = set()

                        invalid_files[iso_20022_message.message_set].add(
                            iso_20022_message
                        )
                else:
                    iso_20022_messages.add(iso_20022_message)

            if message_set in invalid_files:
                iso_20022_messages.update(invalid_files[message_set])
                del invalid_files[message_set]

            if message_set in iso_20022_downloads:
                iso_20022_download = iso_20022_downloads[message_set]
                iso_20022_download.messages.update(iso_20022_messages)
                iso_20022_download.download_links.add(batch_schema_download_link)
            else:
                iso_20022_downloads[message_set] = ISO20022BatchDownload(
                    message_set=message_set,
                    download_links={batch_schema_download_link},
                    messages=iso_20022_messages,
                )
        results_page += 1
    return list(iso_20022_downloads.values())


def download_iso20022_messages(
    driver: webdriver.Chrome,
    messages: List[ISO20022BatchDownload],
) -> ISO20022Metadata:
    metadata = ISO20022Metadata()
    for iso_20022_batch in messages:
        for download_link in iso_20022_batch.download_links:
            request_success = request_download_link(
                download_link=download_link, driver=driver
            )

            if not request_success:
                logger.error(
                    f"unsuccessfully requested the download link: {download_link}"
                )
                continue

            start_time_to_wait = time.time()
            downloaded_filename: Optional[str] = None
            while (
                downloaded_filename is None
                and time.time() - start_time_to_wait < TOTAL_DOWNLOAD_WAIT_TIME
            ):
                downloaded_files = find_zip_files(path=DOWNLOAD_PATH)
                try:
                    downloaded_filename = next(downloaded_files)
                except StopIteration:
                    pass
                time.sleep(DOWNLOAD_WAIT_TIME)

            if downloaded_filename is None:
                logger.error(
                    "unsuccessfully downloaded the schemas for download: "
                    f"{download_link}"
                )
                continue

            downloaded_path = DOWNLOAD_PATH / downloaded_filename
            file_extraction_path = DOWNLOAD_SAVE_PATH / iso_20022_batch.message_set
            extract_zipfile(downloaded_path, file_extraction_path)
            residual_zip_files = find_zip_files(path=file_extraction_path)
            parsing_zip_files = True
            while parsing_zip_files:
                try:
                    zip_filename = next(residual_zip_files)
                except StopIteration:
                    parsing_zip_files = False
                else:
                    zip_file_path = file_extraction_path / zip_filename
                    extract_zipfile(zip_file_path, file_extraction_path)
                    unlink_file(zip_file_path)

            unlink_file(downloaded_path)

            # Find any invalid files that are not in the correct location
            for schema_src in file_extraction_path.iterdir():
                message_set = message_set_from_message_id(message_id=schema_src.stem)
                if message_set != iso_20022_batch.message_set:
                    schema_dst = (
                        file_extraction_path.with_stem(message_set) / schema_src.name
                    )
                    move_file(schema_src, schema_dst)

            logger.info(
                "successfully downloaded "
                f"{iso_20022_batch.message_set} schemas: {downloaded_filename}"
            )
        metadata.update_metadata(batch=iso_20022_batch)
        random_sleep()
    return metadata


if __name__ == "__main__":
    driver: webdriver.Chrome = setup_chrome_driver()

    # Gather all ISO20022 message schema metadata
    messages = gather_iso20022_messages(driver=driver)

    # Clear all XSD schemas that already exist in repository
    clear_all_items_in_path(path=DOWNLOAD_SAVE_PATH)

    # Download all ISO20022 message schemas
    metadata = download_iso20022_messages(driver=driver, messages=messages)
    driver.quit()

    # Save ISO20022 metadata as a JSON file
    # metadata.save_metadata_to_json()
