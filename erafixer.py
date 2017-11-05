#!/usr/bin/env python

import sys
import pandas as pd

PHYSASTRO = ['quantum', 'astro', 'photonics', 'biophotonics']


def main(ERAFILE, author=None, journal=None, discipline=None, sheet_index=None, verbose=False, *args, **kwargs):
    """ Creates a EraFixer object and decides which method to call based on input params """

    erafixer = EraFixer(fn=ERAFILE, sheet_index=sheet_index, verbose=verbose)

    if (author and discipline):
        erafixer.set_discipline(discipline, author, 'AUTHORS')
        erafixer.save()
    elif (journal and discipline):
        erafixer.set_discipline(discipline, journal, 'PARENT_DOC')


class EraFixer(object):
    """ ERA Fixer class """

    def __init__(self, fn=None, sheet_index=None, verbose=False):
        self.sheet_index = 0
        self.verbose = verbose
        self.fn = fn
        self.xls = None
        self.df = None
        self.sheet_index = sheet_index

        self._parse_excel()

        # Specify a writer for saving
        self.writer = pd.ExcelWriter(self.fn, engine='xlsxwriter')

    def set_author_discipline(self, search_term, disc):
        """Sets the discipline based on either the given author or journal

        For each line, if search_term is a substring in AUTHOR and DISCIPLINE field is empty:
            * set DISCIPLINE field to DISC
            * if DISC is not a PhysAstro discipline, set HANDLED=1

        Args:
            search_term (str): Term to be matched, should be full last name or full word from journal
            disc (str): Discipline to be set

        """
        self._print("Setting discipline to '{}' for '{}'".format(disc, search_term))

        matches = self.get_matching_rows(search_term, 'AUTHORS')

        if(len(matches) > 0):
            # Set the discipline on matched rows
            self.df.loc[list(matches.keys()), ('DISCIPLINE')] = disc
            if disc not in PHYSASTRO:
                self._print("'{}' not in PhysAstro, setting HANDLED=1".format(disc))
                self.df.loc[list(matches.keys()), ('HANDLED')] = 1

    def get_matching_rows(self, search_term, column, blank_discipline=True):
        """ Find rows that match the search_term for the given column

        Args:
            search_term (str): Term to be matched, should be full last name or full word from journal
            column (str): Matching column name from spreadsheet

        Returns:
            dict: Dictionary with key values representing the matching indices from the DataFrame and
                values corresponding to the matched column
        """
        # Get rows that have a naive match
        match_indexes = [
            idx
            for idx, row in enumerate(self.df[column])
            if search_term.lower().strip() in row.lower()
        ]

        # Get indexes of match_indexes - NOTE confusing index of indexes
        row_match = {
            match_indexes[idx]: row
            for idx, row in enumerate(self.df.iloc[match_indexes][column])
            if self._match_name(row, search_term)
        }

        # Filter discipline
        if blank_discipline:
            row_match = {
                match_index: row
                for match_index, row in row_match.items()
                if self.df.iloc[match_index].DISCIPLINE == ''
            }
            self._print("Found {} matches for '{}' with empty discipline".format(len(row_match.keys()), search_term))
        else:
            self._print("Found {} matches for '{}'".format(len(row_match.keys()), search_term))

        return row_match

    def get_full_name(self, author_list, search_term):
        """ Returns full matching name in author_list for search_term

        Args:
            author_list (str): Full author list string
            search_term (str): Substring to be used to match full name

        Returns:
            TYPE: Description
        """
        author_list = author_list.lower().strip()
        search_term = search_term.lower().strip()
        full_name = ''

        # Look for search_term in string
        match_start = author_list.find(search_term)
        if(match_start >= 0):
            # Look for full author name between ';' delimiter
            start_name = author_list.rfind(';', 0, match_start)
            end_name = author_list.find(';', match_start)

            # Handle edges
            if start_name < 0:
                start_name = 0
            else:
                start_name += 1

            if end_name < 0:
                end_name = None

            # Extract from author_list and trim
            full_name = author_list[start_name: end_name].strip()

        return full_name

    def save(self):

        # Write dataframe to file (all sheets)
        for sheet in self.xls.sheet_names:
            self._print("Writing sheet '{}' to {}".format(sheet, self.fn))

            if sheet == self.xls.sheet_names[self.sheet_index]:
                self.df.to_excel(self.writer, sheet)
            else:
                self.xls.parse(sheet).to_excel(self.writer, sheet)

        # Save the result
        self.writer.save()

    def _match_name(self, author_list, search_name):
        """ Check if search_name is in author_list

        The search_term should be supplied as the full last name of the author in question.

        Note:
            Names are not stored correctly in the excel sheet (should be in UTF-8) but will still
            match on bad characters.

        Args:
            author_list (str): Full author list string
            search_name (str): Substring to be used to match full name

        Returns:
            bool: If match found, default False
        """
        author_list = author_list.lower().strip()
        search_name = search_name.lower().strip()
        found = False

        # Get the name
        full_name = self.get_full_name(author_list, search_name)

        # Test if search_name matches a whole name word (i.e. is it the full last name?)
        full_name_split = full_name.split()
        found = search_name in full_name_split

        return found

    def _parse_excel(self):
        """Parse the excel file and return a `pandas.DataFrame` for sheet

        Note: If more than one sheet exists and no `--sheet_index` has been given,
            force a prompt to clarify
        """
        self._print("Parsing file {}".format(self.fn))
        try:
            self.xls = pd.ExcelFile(self.fn)
        except Exception:
            print("Can't find excel file: {}".format(self.fn))
            sys.exit(1)

        if (len(self.xls.sheet_names) > 1) and not self.sheet_index:
            print("More than one sheet is present, please select: ")
            for idx, sheet in enumerate(self.xls.sheet_names):
                print("{} - {}".format(idx, sheet))

            self.sheet_index = int(input("Sheet index: "))
            print("Pass --sheet_index={} to avoid this step".format(self.sheet_index))

        self._print("Using sheet index {} - {}".format(self.sheet_index, self.xls.sheet_names[self.sheet_index]))
        self.df = self.xls.parse(self.xls.sheet_names[self.sheet_index])

        if 'HANDLED' not in self.df.columns:
            self._print("Adding HANDLED (default 0) column to spreadsheet")
            self.df['HANDLED'] = 0

        if 'DISCIPLINE' not in self.df.columns:
            self._print("Adding DISCIPLINE (default '') column to spreadsheet")
            self.df['DISCIPLINE'] = ''

    def _print(self, msg):
        """ Simple wrapper to check verbose flag """
        if self.verbose:
            print(msg)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description="Process and update ERA codes")
    parser.add_argument('ERAFILE', help='ERA file as excel spreadsheet')
    parser.add_argument('--detect_author', dest='author',
                        help='Part of the author name in AUTHOR column, should be unique substring')
    parser.add_argument('--detect_journal', dest='journal',
                        help='Part of the author name in JOURNAL column, should be unique substring')
    parser.add_argument('--set_discipline', dest='discipline',
                        help='Discipline to be set')
    parser.add_argument('--split_disciplines', action='store_true',
                        help='Split ERAFILE into different files called <PREFIX>_<DISC>.xlsx for each discipline')
    parser.add_argument('--prefix', help='Prefix for split-disciplines')
    parser.add_argument('--carry_forward_forcs', action='store_true',
                        help='Carry 2015 codes forward into the corresponding 2018 columns')
    parser.add_argument('--set_forc', dest='forc_string',
                        help='Apply the FORC string')
    parser.add_argument('--justify', dest='justify_string',
                        help='Justification string [optional for --set_forc]')
    parser.add_argument('--sheet_index', default=None,
                        help="Excel sheet to use, defaults to first sheet")
    parser.add_argument('--verbose', action='store_true', default=False,
                        help="Show some output, default false")

    args = parser.parse_args()

    # Do some argument checking
    if (args.author and not args.discipline):
        parser.error(
            "Setting an author discipline requires both --detect_author and -set_discipline to be set")

    if (args.journal and not args.discipline):
        parser.error(
            "Setting a journal discipline requires both --detect_author and -set_discipline to be set")

    if (args.discipline and not (args.author or args.journal)):
        parser.error(
            "Setting a discipline requires either --detect_author or --detect_journal to be set")

    if (args.split_disciplines and not args.prefix) or (not args.split_disciplines and args.prefix):
        parser.error(
            "Splitting the file requires both --split_disciplines and a --prefix to be set")

    if (args.justify_string and not args.set_forc):
        parser.error(
            "The justify string is only used with the --set_forc option")

    if not ((args.author and args.discipline) or (args.split_disciplines and args.prefix) or args.carry_forward_forcs):
        parser.print_help()
        print("\nNo commands given")
        parser.exit()

    main(**vars(args))
