"""Run directly from a source checkout, without an editable-install hook."""

from tg_ascii.__main__ import main


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # process_decoding: decoder processes in the packaged app.
    main()
