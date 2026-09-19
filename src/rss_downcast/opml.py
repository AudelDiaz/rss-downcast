"""OPML import/export."""

import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def export_opml(conn, output_path):
    """Export all feeds to an OPML file. Returns feed count."""
    if output_path is None:
        raise ValueError('output_path required')
    rows = conn.execute(
        'SELECT feed_url, feed_title FROM feeds ORDER BY feed_id'
    ).fetchall()

    opml = ET.Element('opml', version='2.0')
    head = ET.SubElement(opml, 'head')
    ET.SubElement(head, 'title').text = 'rss-downcast Feeds'
    body = ET.SubElement(opml, 'body')
    for feed_url, feed_title in rows:
        ET.SubElement(
            body,
            'outline',
            type='rss',
            text=feed_title or feed_url,
            title=feed_title or feed_url,
            xmlUrl=feed_url,
        )

    tree = ET.ElementTree(opml)
    if hasattr(ET, 'indent'):
        ET.indent(tree, space='  ')
    tree.write(output_path, encoding='utf-8', xml_declaration=True)
    logging.info('Exported %s feed(s) to %s', len(rows), output_path)
    return len(rows)


def import_opml(conn, input_path):
    """Import feeds from an OPML file. Returns (imported, skipped)."""
    if input_path is None or not os.path.exists(input_path):
        raise FileNotFoundError(f'OPML file not found: {input_path}')
    tree = ET.parse(input_path)
    root = tree.getroot()
    urls = []
    for outline in root.iter('outline'):
        xml_url = None
        for k, v in outline.attrib.items():
            if k.lower() == 'xmlurl':
                xml_url = v
                break
        if xml_url:
            title = outline.get('text') or outline.get('title') or xml_url
            urls.append((xml_url.strip(), title.strip()))

    if not urls:
        logging.warning('No feeds found in OPML: %s', input_path)
        return (0, 0)

    existing_rows = conn.execute('SELECT feed_url FROM feeds').fetchall()
    existing_norm = {r[0].strip().rstrip('/').lower() for r in existing_rows if r[0]}

    imported = 0
    skipped = 0
    cursor = conn.cursor()
    for feed_url, feed_title in urls:
        norm = feed_url.strip().rstrip('/').lower()
        if norm in existing_norm:
            skipped += 1
            continue
        cursor.execute('SELECT feed_id FROM feeds WHERE feed_url = ?', (feed_url,))
        if cursor.fetchone():
            skipped += 1
            existing_norm.add(norm)
            continue
        cursor.execute(
            'INSERT INTO feeds (feed_url, feed_title) VALUES (?, ?)',
            (feed_url, feed_title),
        )
        imported += 1
        existing_norm.add(norm)
    conn.commit()
    logging.info('Imported %s feed(s), skipped %s existing', imported, skipped)
    return (imported, skipped)


def export_opml_to_path(db_path_conn_factory, output_path):
    """Helper used by CLI: open conn via factory, export, close. Returns count."""
    with db_path_conn_factory() as conn:
        return export_opml(conn, Path(output_path))
