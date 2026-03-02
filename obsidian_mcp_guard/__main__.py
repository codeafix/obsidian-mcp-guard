from .server import create_vault_server


def main():
    create_vault_server().run(transport="stdio")


if __name__ == "__main__":
    main()
