# ISO20022 Message Catalogue

A lightweight Python script that automatically downloads and tracks ISO20022 message XSD schemas daily, providing a centralized and up-to-date repository of schemas and associated metadata. Ideal for financial developers, analysts, or anyone working with ISO20022 messages.

## Features

- Downloads all available ISO20022 XSD schemas daily.
- Generates and updates a JSON file containing metadata for each schema.
- Provides detailed information about each schema, including its filename, identifier, name, submitting organization and download link.
- Includes a GitHub Action that runs the downloader daily at midnight, ensuring the repository stays current.

## Repository Structure

```plaintext
iso20022-message-catalogue/
├── .github/workflows/     # CI/CD workflows
├── .gitignore             # Git ignore file
├── LICENSE                # Project license
├── README.md              # Project documentation
├── iso20022-schemas/      # Directory to store downloaded XSD schemas
├── iso20022_messages.json # JSON file with metadata for schemas
├── requirements.txt       # Python dependencies
├── scraper.py             # The main downloader script
```

## How It Works

The script `scraper.py` fetches all available ISO20022 message XSD schemas and saves them in the `iso20022-schemas/` directory. It also updates `iso20022_messages.json`, a JSON file that contains metadata for each schema, such as its filename, identifier and name.

A GitHub Action is configured to run `scraper.py` every day at midnight (UTC). This ensures the XSD schemas and metadata remain up to date.

Here’s an example entry from `iso20022_messages.json`:

```json
"acmt.001.001.08.xsd": {
    "message_id": "acmt.001.001.08",
    "message_name": "AccountOpeningInstructionV08",
    "submitting_organization": "SWIFT",
    "download_link": "https://www.iso20022.org/message/20266/download"
}
```

## Installation

Clone the repository:

```bash
git clone https://github.com/galactixx/iso20022-message-catalogue.git
```

Navigate to the project directory:

```bash
cd iso20022-message-catalogue
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the downloader script manually:

```bash
python scraper.py
```

This will download the latest XSD schemas and update the `iso20022_messages.json` file with their metadata.

Alternatively, rely on the GitHub Action to automatically update the schemas and metadata daily.

Access the schemas in the `iso20022-schemas/` directory and metadata in `iso20022_messages.json` for integration into other projects or analysis.

## License

This project is licensed under the MIT License.

## Acknowledgments

This project was inspired by the need to maintain an up-to-date repository of ISO20022 message schemas, providing a valuable resource for developers and analysts in the financial sector.