#!/usr/bin/env python

import sys
import pandas as pd
import re

PHYSASTRO = ['quantum', 'astro', 'photonics', 'biophotonics']
COL_LOOKUP = {
    'author': 'AUTHORS',
    'journal': 'PARENT_DOC',
    'for1_e15': 'FOR1_E15',
    'for1perc_e15': 'FOR1PERC_E15',
    'for2_e15': 'FOR2_E15',
    'for2perc_e15': 'FOR2PERC_E15',
    'for3_e15': 'FOR3_E15',
    'for3perc_e15': 'FOR3PERC_E15',
    'for4_e15': 'FOR4_E15',
    'for4perc_e15': 'FOR4PERC_E15',
    'for1_e18': 'ERA_18_FOR1',
    'for1perc_e18': 'ERA_18_FOR1%',
    'for2_e18': 'ERA_18_FOR2',
    'for2perc_e18': 'ERA_18_FOR2%',
    'for3_e18': 'ERA_18_FOR3',
    'for3perc_e18': 'ERA_18_FOR3%',
    'for4_e18': 'ERA_18_FOR4',
    'for4perc_e18': 'ERA_18_FOR4%',
    'clawback': 'ERA_18_FOR4_ClawBack_Justify'
}


forc_re = re.compile('''
    (?P<code1>\d{2,4}):?(?P<code1_perc>\d{2})?,?
    (?P<code2>\d{2,4})?:?(?P<code2_perc>\d{2})?,?
    (?P<code3>\d{2,4})?:?(?P<code3_perc>\d{2})?,?
''', re.X)


def main(ERAFILE,
         author=None,
         journal=None,
         discipline=None,
         split_disciplines=False,
         prefix=None,
         carry_forward_forcs=False,
         forc_string=None,
         justify_string=None,
         sheet_index=None,
         verbose=False,
         *args, **kwargs
         ):
    """ Creates a EraFixer object and decides which method to call based on input params """

    erafixer = EraFixer(fn=ERAFILE, sheet_index=sheet_index, verbose=verbose)

    if (author and discipline):
        erafixer.set_discipline(discipline, author, COL_LOOKUP['author'])
        erafixer.save()
    elif (journal and discipline):
        erafixer.set_discipline(discipline, journal, COL_LOOKUP['journal'])
        erafixer.save()
    elif split_disciplines:
        erafixer.split_disciplines(prefix)
    elif carry_forward_forcs:
        erafixer.carry_forward_forcs()
        erafixer.save()
    elif forc_string:
        erafixer.set_forc_string(forc_string, justify_string=justify_string, author=author, journal=journal)
        erafixer.save()


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

    def set_author_discipline(self, search_term, disc):
        """ Thin-wrapper around `set_discipline` with `column="AUTHORS"`search_term

        See docstring for `set_discipline`
         """
        self.set_discipline(search_term, disc, COL_LOOKUP['author'])

    def set_journal_discipline(self, search_term, disc):
        """ Thin-wrapper around `set_discipline` with `column="PARENT_DOC"`search_term

        See docstring for `set_discipline`
         """
        self.set_discipline(search_term, disc, COL_LOOKUP['journal'])

    def set_discipline(self, search_term, disc, column):
        """Sets the discipline based on either the given author or journal

        For each line, if search_term is a substring in AUTHOR|PARENT_DOC and DISCIPLINE field is empty:
            * set DISCIPLINE field to DISC
            * if DISC is not a PhysAstro discipline, set HANDLED=1

        Args:
            search_term (str): Term to be matched, should be full last name or full word from journal
            disc (str): Discipline to be set

        """
        self._print("Setting discipline to '{}' for '{}'".format(disc, search_term))

        matches = self.get_matching_rows(search_term, column)

        if(len(matches) > 0):
            # Set the discipline on matched rows
            self.df.loc[list(matches.keys()), ('DISCIPLINE')] = disc
            if disc not in PHYSASTRO:
                self._print("'{}' not in PhysAstro, setting HANDLED=1".format(disc))
                self.df.loc[list(matches.keys()), ('HANDLED')] = 1

    def split_disciplines(self, prefix):
        """Output an excel file for each discipline with filename PREFIX_DISC.xlsx

        Args:
            prefix (str): Prefix for filename

        Returns:
            list(str): List of saved file names
        """
        disc_list = self.df.DISCIPLINE.unique()

        save_list = list()

        for disc in disc_list:
            if str(disc) in ['', 'nan']:
                continue

            df = self.df.query('DISCIPLINE == "{}"'.format(disc))
            save_name = self.save(df=df, save_name='{}_{}'.format(prefix, disc))
            save_list.append(save_name)

        return save_list

    def carry_forward_forcs(self):
        """ For each line, if there are values for 2015 FOR codes and HANDLED

        """
        # Find rows that are not handled yet
        matches = self.get_matching_rows(0, 'HANDLED', blank_discipline=False)

        if(len(matches) > 0):
            self._print("Copying 2015 FOR codes to 2018 for unhandled rows")

            not_handled = self.df.HANDLED == 0
            for col_2015 in COL_LOOKUP.keys():
                if 'e15' not in col_2015:
                    continue

                col_2018 = col_2015.replace('e15', 'e18')

                col_has_values = self.df.loc[not_handled, (COL_LOOKUP[col_2015])].apply(str) != 'nan'
                condition = col_has_values[col_has_values].index

                self.df.loc[condition, (COL_LOOKUP[col_2018])] = \
                    self.df.loc[condition, (COL_LOOKUP[col_2015])]

                self.df.loc[condition, ('HANDLED')] = 1

    def set_forc_string(self, forc_string, justify_string=None, author=None, journal=None):
        match = forc_re.match(forc_string)
        if match is None:
            self._print("FORC_STRING not valid")
            return

        self._print("Applying FORC_STRING '{}'".format(forc_string))
        code1 = match.group('code1')
        code1_perc = match.group('code1_perc')
        code2 = match.group('code2')
        code2_perc = match.group('code2_perc')
        code3 = match.group('code3')
        code3_perc = match.group('code3_perc')

        # Get matching rows
        if author:
            matches = self.get_matching_rows(author, COL_LOOKUP['author'], skip_handled=True, blank_discipline=False)
        elif journal:
            matches = self.get_matching_rows(journal, COL_LOOKUP['journal'], skip_handled=True, blank_discipline=False)
        else:
            matches = self.get_matching_rows(0, 'HANDLED', skip_handled=True, blank_discipline=False)

        # Get codes for 2018

        return matches

    def get_matching_rows(self, search_term, column, skip_handled=False, blank_discipline=True):
        """Find rows that match the search_term for the given column

        Args:
            search_term (str): Term to be matched, should be full last name or full word from journal
            column (str): Matching column name from spreadsheet
            blank_discipline (bool, optional): Should matching rows have a blank discipline, default True

        Returns:
            dict: Dictionary with key values representing the matching indices from the DataFrame and
                values corresponding to the matched column
        """
        # Get rows that have a naive match
        match_indexes = [
            idx
            for idx, row in enumerate(self.df[column])
            if str(search_term).lower().strip() in str(row).lower()
        ]

        # Get indexes of match_indexes - NOTE confusing index of indexes
        row_match = {
            match_indexes[idx]: row
            for idx, row in enumerate(self.df.iloc[match_indexes][column])
            if self._match_name(row, search_term, column)
        }

        # Filter discipline
        if blank_discipline:
            row_match = {
                match_index: row
                for match_index, row in row_match.items()
                if self.df.iloc[match_index].DISCIPLINE == ''
            }
            self._print("Found {} matches for '{}' with empty discipline".format(len(row_match.keys()), search_term))
        elif skip_handled:
            row_match = {
                match_index: row
                for match_index, row in row_match.items()
                if self.df.iloc[match_index].HANDLED == 0
            }
            self._print("Found {} matches for '{}' with HANDLED=0".format(len(row_match.keys()), search_term))
        else:
            self._print("Found {} matches for {}={}".format(len(row_match.keys()), column, search_term))

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

    def get_journal_name(self, journal_name, search_term):
        """ Returns full matching name in journal_name for search_term

        Args:
            journal_name (str): Full journal list string
            search_term (str): Substring to be used to match full name

        Returns:
            TYPE: Description
        """
        journal_name = journal_name.lower().strip()
        search_term = search_term.lower().strip()
        full_name = ''

        # Look for search_term in string
        match_start = journal_name.find(search_term)
        if(match_start >= 0):
            full_name = journal_name

        return full_name

    def save(self, df=None, save_name=None):

        if df is not None:
            if not save_name:
                print("Can't save a DataFrame without a save_name")
            else:
                if not save_name.endswith('.xlsx'):
                    save_name += '.xlsx'

                self._print("Writing dataframe to {} with {} records".format(save_name, len(df)))
                writer = pd.ExcelWriter(save_name, engine='xlsxwriter')
                df.to_excel(writer)
                writer.save()
        else:
            save_name = self.fn
            # Specify a writer for saving
            writer = pd.ExcelWriter(save_name, engine='xlsxwriter')

            # Write dataframe to file (all sheets)
            for sheet in self.xls.sheet_names:
                self._print("Writing sheet '{}' to {}".format(sheet, save_name))

                if sheet == self.xls.sheet_names[self.sheet_index]:
                    self.df.to_excel(writer, sheet)
                else:
                    self.xls.parse(sheet).to_excel(writer, sheet)

            # Save the result
            writer.save()

        return save_name

    def _match_name(self, full_string, search_name, column):
        """ Check if search_name is in full_string

        The search_term should be supplied as the full last name of the author in question.

        Note:
            Names are not stored correctly in the excel sheet (should be in UTF-8) but will still
            match on bad characters.

        Args:
            full_string (str): Full author list string
            search_name (str): Substring to be used to match full name

        Returns:
            bool: If match found, default False
        """
        full_string = str(full_string).lower().strip()
        search_name = str(search_name).lower().strip()
        found = False

        # Get the name
        if column == COL_LOOKUP['author']:
            full_name = self.get_full_name(full_string, search_name)
            full_name = full_name.split()
        elif column == COL_LOOKUP['journal']:
            full_name = self.get_journal_name(full_string, search_name)
        else:
            full_name = full_string

        # Test if search_name matches a word in string
        # Note: For AUTHORS this is a list of strings, for journals a string
        found = search_name in full_name

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
        elif not self.sheet_index:
            self.sheet_index = 0

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
    parser.add_argument('--sheet_index', default=None, type=int,
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

    if (args.justify_string and not args.forc_string):
        parser.error(
            "The justify string is only used with the --set_forc option")

    if args.forc_string:
        match = forc_re.match(args.forc_string)
        if match is None:
            parser.error("FORC_STRING not valid")

    if not ((args.author and args.discipline) or
            (args.split_disciplines and args.prefix) or
            args.carry_forward_forcs or
            args.forc_string
            ):
        parser.print_help()
        print("\nNo commands given")
        parser.exit()

    main(**vars(args))
