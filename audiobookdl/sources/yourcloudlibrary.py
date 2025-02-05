from ..utils import logging
from ..utils.source import Source
from ..utils import logging
from ..utils.exceptions import UserNotAuthorized, RequestError
from ..utils.audiobook import AudiobookFile
import requests.utils
import base64
from typing import Dict, List

class YourCloudLibrarySource(Source):
    requires_cookies = True
    require_username_and_password = True
    match = [
        r"https?://ebook.yourcloudlibrary.com/library/[^/]+/AudioPlayer/.+"
    ]
    meta: Dict
    playlist: Dict

    def get_title(self):
        return self.book_info["Title"]

    def get_files(self) -> List[AudiobookFile]:
        files = []
        for f in self.playlist["playlist"]:
            files.append(AudiobookFile(
                url = f["url"],
                ext = "mp3"
            ))
        return files

    def get_metadata(self):
        metadata = {}
        if not self.meta is None:
            try:
                audiobook = self.meta["audiobook"]
                metadata["authors"] = audiobook["authors"]
                metadata["narrators"] = audiobook["narrators"]
                if audiobook["series"] is not None and len(audiobook["series"]) >= 1:
                    metadata["series"] = audiobook["series"][0]
            except:
                return {}
        return metadata

    def get_cover(self):
        return self.get(self.meta['audiobook']['cover_url'])

    def _get_library_id(self):
        return self.url.split("/")[-3]


    def _get_fullfillmenttoken(self):
        token_base64 = self.find_in_page(
            self.url,
            r"(?<=(\"Osi\":\"x-))[^\"]+",
            cookies=requests.utils.dict_from_cookiejar(self._session.cookies),
        )
        if token_base64 is None:
            raise UserNotAuthorized
        token = base64.b64decode(token_base64).decode('utf8')
        logging.debug(f"{token=}")
        return token

    def _get_bookinfo(self):
        # Get list of borrowed books
        library = self._get_library_id()
        borrowed = self.get_json(
                f"https://ebook.yourcloudlibrary.com/uisvc/{library}/Patron/Borrowed",
                cookies=requests.utils.dict_from_cookiejar(self._session.cookies),
        )
        if borrowed is None:
            raise UserNotAuthorized
        # Find the matching book in list of borrowed books
        url_id = self.url.split("/")[-1]
        book_info = None
        for i in borrowed:
            if i["Id"] == url_id:
                book_info = i
        if book_info is None:
            raise UserNotAuthorized
        return book_info

    def _authenticate(self):
        library = self._get_library_id()
        resp = self.post(
            f"https://ebook.yourcloudlibrary.com/uisvc/{library}/Patron/LoginPatron",
            data = {
                "UserId": self.username,
                "Password": self.password
            }
        )
        logging.debug(f"Authentication response {resp}")


    def before(self):
        if self.username and self.password:
            self._authenticate()
        self.book_info = self._get_bookinfo()
        token = self._get_fullfillmenttoken()
        library = self._get_library_id()
        audioplayer = self.post_json(f"https://ebook.yourcloudlibrary.com/uisvc/{library}/AudioPlayer",
                data={"url": f"{self.book_info['fulfillmentTokenUrl']}&token={token}"})
        if audioplayer is None:
            raise RequestError
        fulfillment_id = audioplayer["fulfillmentId"]
        account_id = audioplayer["accountId"]
        headers = {"Session-Key": audioplayer["sessionKey"]}
        self.meta = self.get_json(
            f"https://api.findawayworld.com/v4/accounts/{account_id}/audiobooks/{fulfillment_id}",
            headers=headers
        )
        logging.debug(f"{self.meta=}")
        self.playlist = self.post_json(
            f"https://api.findawayworld.com/v4/audiobooks/{fulfillment_id}/playlists",
            data='{"license_id":"' + audioplayer["licenseId"] + '"}',
            headers=headers)
        if self.playlist is None:
            raise UserNotAuthorized
