import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def number(text):
    return int(text.replace(',', '').strip() or '0')


def fetch_profile(session, scholar_id, start=0):
    response = session.get(
        'https://scholar.google.com/citations',
        params={'hl': 'en', 'user': scholar_id, 'pagesize': 100, 'cstart': start},
        timeout=30,
    )
    print(f'Google Scholar: HTTP {response.status_code}', flush=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    if soup.select_one('#gsc_prf_in') is None:
        raise RuntimeError('The response does not contain a Google Scholar author profile')
    return soup, response.url



def parse_profile(soup, scholar_id):
    stats = soup.select('#gsc_rsb_st .gsc_rsb_std')
    if len(stats) != 6:
        raise ValueError('Google Scholar citation metrics are missing')
    author = {
        'container_type': 'Author',
        'filled': ['basics', 'publications', 'indices', 'counts'],
        'scholar_id': scholar_id,
        'source': 'AUTHOR_PROFILE_PAGE',
        'name': soup.select_one('#gsc_prf_in').get_text(strip=True),
        'affiliation': soup.select_one('.gsc_prf_il').get_text(' ', strip=True),
        'interests': [node.get_text(strip=True) for node in soup.select('#gsc_prf_int a')],
        'publications': {},
        'cites_per_year': {
            year.get_text(): number(count.get_text())
            for year, count in zip(soup.select('.gsc_g_t'), soup.select('.gsc_g_al'))
        },
    }
    for key, cell in zip(
        ('citedby', 'citedby5y', 'hindex', 'hindex5y', 'i10index', 'i10index5y'), stats
    ):
        author[key] = number(cell.get_text())
    org = soup.select_one('.gsc_prf_il a[href*="org="]')
    if org:
        author['organization'] = int(parse_qs(urlparse(org['href']).query)['org'][0])
    email = soup.select_one('#gsc_prf_ivh')
    if email:
        match = re.search(r'Verified email at (\S+)', email.get_text())
        if match:
            author['email_domain'] = '@' + match.group(1)
    return author


def add_publications(author, soup, base_url):
    for row in soup.select('.gsc_a_tr'):
        title = row.select_one('.gsc_a_at')
        pub_id = parse_qs(urlparse(title['href']).query)['citation_for_view'][0]
        citations = row.select_one('.gsc_a_ac')
        count = citations.get_text(strip=True).replace('*', '')
        year = row.select_one('.gsc_a_y')
        publication = {
            'container_type': 'Publication',
            'source': 'AUTHOR_PUBLICATION_ENTRY',
            'bib': {'title': title.get_text(strip=True), 'pub_year': year.get_text(strip=True)},
            'filled': False,
            'author_pub_id': pub_id,
            'num_citations': number(count),
        }
        if citations.get('href'):
            citedby_url = urljoin(base_url, citations['href'])
            publication['citedby_url'] = citedby_url
            publication['cites_id'] = parse_qs(urlparse(citedby_url).query).get('cites', [])
        author['publications'][pub_id] = publication


def main():
    scholar_id = os.environ['GOOGLE_SCHOLAR_ID']
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en-US,en;q=0.9'})
        soup, url = fetch_profile(session, scholar_id)
        author = parse_profile(soup, scholar_id)
        while True:
            add_publications(author, soup, url)
            more = soup.select_one('#gsc_bpf_more')
            if more is None or more.has_attr('disabled'):
                break
            soup, url = fetch_profile(session, scholar_id, len(author['publications']))
    author['updated'] = datetime.now(timezone.utc).isoformat()
    results = Path('results')
    results.mkdir(exist_ok=True)
    (results / 'gs_data.json').write_text(json.dumps(author, ensure_ascii=False, indent=2), encoding='utf-8')
    shield = {'schemaVersion': 1, 'label': 'citations', 'message': str(author['citedby'])}
    (results / 'gs_data_shieldsio.json').write_text(json.dumps(shield), encoding='utf-8')
    print(f"Updated {author['name']}: {author['citedby']} citations across {len(author['publications'])} publications")


if __name__ == '__main__':
    main()
