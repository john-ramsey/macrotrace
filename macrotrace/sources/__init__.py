def create_tables(db, tables):
    with db:
        db.create_tables(tables)


def drop_tables(db, tables):
    with db:
        db.drop_tables(tables)
