#!/usr/bin/env python

import os
import sys
import numpy as np
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
         debug=False,
         *args, **kwargs
         ):
    """ Creates a EraFixer object and decides which method to call based on input params """

    erafixer = EraFixer(fn=ERAFILE, sheet_index=sheet_index, verbose=verbose, debug=debug)

    if (author and discipline):
        erafixer.set_author_discipline(author, discipline)
        erafixer.save()
    elif (journal and discipline):
        erafixer.set_journal_discipline(journal, discipline)
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

    def __init__(self, fn=None, sheet_index=None, verbose=False, debug=False):
        assert os.path.exists(fn)
        self.verbose = verbose
        self.debug = debug

        self.sheet_index = 0
        self.fn = fn
        self.xls = None
        self.df = None
        self.sheet_index = sheet_index

        self._parse_excel()

    def set_author_discipline(self, search_term, disc):
        """ Thin-wrapper around `set_discipline` with author column name

        See docstring for `set_discipline`
         """
        self.set_discipline(search_term, disc, COL_LOOKUP['author'])

    def set_journal_discipline(self, search_term, disc):
        """ Thin-wrapper around `set_discipline` with journal column name

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

        matching_indices = self.get_matching_rows(search_term, column)

        # Set the discipline on matched rows
        self._print("Setting discipline to '{}' for '{}' on {} rows".format(disc, search_term, len(matching_indices)))
        self.df.loc[matching_indices, ('DISCIPLINE')] = disc
        if disc not in PHYSASTRO:
            self._print("'{}' not in PhysAstro, setting HANDLED=1".format(disc))
            self.df.loc[matching_indices, ('HANDLED')] = 1

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
        self._print("Copying 2015 FOR codes to 2018 for unhandled rows")

        # Find rows that are not handled yet
        matching_indices = self.get_matching_rows(0, 'HANDLED', blank_discipline=False)
        self._print("Found {} total unhandled rows".format(len(matching_indices)))

        for col_2015 in COL_LOOKUP.keys():
            # Only looking at _e15 FOR code columns
            if 'e15' not in col_2015:
                continue

            col_2018 = col_2015.replace('e15', 'e18')

            # Find 2015 columns that do not have blank values
            has_2015_mask = pd.notnull(self.df.loc[matching_indices, (COL_LOOKUP[col_2015])])

            self._print("Moving {} values to {}".format(has_2015_mask.sum(), col_2018))

            # Copy to 2018 columns
            self.df.loc[has_2015_mask, (COL_LOOKUP[col_2018])] = \
                self.df.loc[has_2015_mask, (COL_LOOKUP[col_2015])]

            # Mark row as handled
            self.df.loc[has_2015_mask, ('HANDLED')] = 2

    def set_forc_string(self, forc_string, justify_string=None, author=None, journal=None):
        self._print("Applying FORC_STRING '{}'".format(forc_string))

        try:
            code1, code1_perc, code2, code2_perc, code3, code3_perc = self._parse_forc_string(forc_string)
        except Exception as e:
            self._print(e)
            return

        # Get matching rows
        if author:
            matching_indices = self.get_matching_rows(
                author, COL_LOOKUP['author'], skip_handled=True, blank_discipline=False)
        elif journal:
            matching_indices = self.get_matching_rows(
                journal, COL_LOOKUP['journal'], skip_handled=True, blank_discipline=False)
        else:
            matching_indices = self.get_matching_rows(0, 'HANDLED', skip_handled=True, blank_discipline=False)

        for idx, row in self.df.loc[matching_indices].iterrows():
            # Save the FORC_STRING
            self.df.set_value(idx, 'FORC_STRING', forc_string)

            default_code1 = str(row.loc[COL_LOOKUP['for1_e18']])
            default_code2 = str(row.loc[COL_LOOKUP['for2_e18']])
            default_code3 = str(row.loc[COL_LOOKUP['for3_e18']])

            if(default_code1 == 'nan'):
                default_code1 = ''
            if(default_code2 == 'nan' or default_code2 == 'None'):
                default_code2 = ''
            if(default_code3 == 'nan' or default_code3 == 'None'):
                default_code3 = ''

            # If MD, apply codes
            if ('MD' in default_code1) or ('MD' in default_code2) or ('MD' in default_code2):
                self._debug("Found 'MD', applying codes and marking HANDLED=1")
                self.df.set_value(idx, COL_LOOKUP['for1_e18'], code1)
                self.df.set_value(idx, COL_LOOKUP['for2_e18'], code2)
                self.df.set_value(idx, COL_LOOKUP['for3_e18'], code3)
                self.df.set_value(idx, COL_LOOKUP['for1perc_e18'], code1_perc)
                self.df.set_value(idx, COL_LOOKUP['for2perc_e18'], code2_perc)
                self.df.set_value(idx, COL_LOOKUP['for3perc_e18'], code3_perc)

                # Mark handled
                self.df.set_value(idx, 'HANDLED', 1)

                continue

            # Correct some string/float ugliness and add prefix 0
            if default_code1 > '' and not default_code1.startswith('0'):
                default_code1 = ('0' + default_code1).replace('.0', '')
            if default_code2 is not None and default_code2 > '' and not default_code2.startswith('0'):
                default_code2 = ('0' + default_code2).replace('.0', '')
            if default_code3 is not None and default_code3 > '' and not default_code3.startswith('0'):
                default_code3 = ('0' + default_code3).replace('.0', '')

            # If all the requested codes are present,
            # or their 2 digit forms are present, (eg 0206 is fine if 02 is listed)
            default_code1_present = default_code1 > ''
            default_code2_present = default_code2 > ''
            default_code3_present = default_code3 > ''

            code1_present = code1 is not None and code1 > '' and code1.startswith(default_code1)
            code2_present = code2 is not None and code2 > '' and code2.startswith(default_code2)
            code3_present = code3 is not None and code3 > '' and code3.startswith(default_code3)

            provided_codes = (code1_present, code2_present, code3_present)
            default_codes = (default_code1_present, default_code2_present, default_code3_present)

            if provided_codes == default_codes:
                self._debug("All codes present, applying FORC_STRING and marking HANDLED=1")
                self.df.set_value(idx, COL_LOOKUP['for1_e18'], code1)
                self.df.set_value(idx, COL_LOOKUP['for2_e18'], code2)
                self.df.set_value(idx, COL_LOOKUP['for3_e18'], code3)
                self.df.set_value(idx, COL_LOOKUP['for1perc_e18'], code1_perc)
                self.df.set_value(idx, COL_LOOKUP['for2perc_e18'], code2_perc)
                self.df.set_value(idx, COL_LOOKUP['for3perc_e18'], code3_perc)

                # Mark handled
                self.df.set_value(idx, 'HANDLED', 1)
            else:
                # If some of the requested codes are not present
                # (and not saved by MD or 2 digit codes)
                # and --justify flag is not present
                # set HANDLED=99
                if justify_string is None:
                    self._debug("Not all codes present and not justify, marking HANDLED=99")
                    # Mark ClawbackNeeded
                    self.df.HANDLED = self.df.HANDLED.apply(str)
                    self.df.set_value(idx, 'HANDLED', 99)
                else:
                    # First check if code is missing (blank)
                    missing_code_1 = default_code1_present and not code1_present
                    missing_code_2 = default_code2_present and not code2_present
                    missing_code_3 = default_code3_present and not code3_present

                    # Then check if code doesn't match (NOTE: The above is probably
                    # redundant but a little cleaner to read)
                    missing_code_1 = missing_code_1 or (default_code1 != code1)
                    missing_code_2 = missing_code_2 or (default_code2 != code2)
                    missing_code_3 = missing_code_3 or (default_code3 != code3)

                    if missing_code_1:
                        self._debug("Missing code 1, Default: {} \t Provided: {}".format(default_code1, code1))

                    if missing_code_2:
                        self._debug("Missing code 2, Default: {} \t Provided: {}".format(default_code2, code2))

                    if missing_code_3:
                        self._debug("Missing code 3, Default: {} \t Provided: {}".format(default_code3, code3))

                    # One code, not present - have justify
                    if (missing_code_1 and not code2_present and not code3_present):
                        self._debug("One code given but not present, setting justify")
                        # Assign code to FOR4 and set percent=100, clawback=justify, set HANDLED=1
                        self.df.set_value(idx, COL_LOOKUP['for4_e18'], code1)
                        self.df.set_value(idx, COL_LOOKUP['for4perc_e18'], 100)
                        self.df.set_value(idx, COL_LOOKUP['clawback'], justify_string)
                        self.df.set_value(idx, 'HANDLED', 1)
                        continue

                    # Multiple codes, one not present - have justify
                    if (code1_present and (missing_code_2 or missing_code_3)):
                        self._debug("Multiple codes given but not present, setting justify")
                        if missing_code_2:
                            if code2_perc >= 66:
                                self.df.set_value(idx, COL_LOOKUP['for4_e18'], code2)
                                self.df.set_value(idx, COL_LOOKUP['for4perc_e18'], code2_perc)
                                self._debug("Missing code is greater than 66%, putting in FOR4 and setting HANDLED=1")

                                # Set code 1 to remaining percentage
                                self.df.set_value(idx, COL_LOOKUP['for1perc_e18'], 100 - code2_perc)

                                self.df.set_value(idx, 'HANDLED', 1)
                            else:
                                self._debug("Missing code is less than 66%, setting HANDLED=99")
                                self.df.set_value(idx, 'HANDLED', 99)

                        elif missing_code_3:
                            if code3_perc >= 66:
                                self.df.set_value(idx, COL_LOOKUP['for4_e18'], code3)
                                self.df.set_value(idx, COL_LOOKUP['for4perc_e18'], code3_perc)
                                self._debug("Missing code is greater than 66%, putting in FOR4 and setting HANDLED=1")

                                # Set code 1 and 2 to remaining percentage split evenly
                                self.df.set_value(idx, COL_LOOKUP['for1perc_e18'], 100 - int(code3_perc / 2))
                                self.df.set_value(idx, COL_LOOKUP['for2perc_e18'], 100 - int(code3_perc / 2))

                                self.df.set_value(idx, 'HANDLED', 1)
                            else:
                                self._debug("Missing code is less than 66%, setting HANDLED=99 (ClawbackNeeded)")
                                self.df.set_value(idx, 'HANDLED', 99)

                        elif(code1_present and code2_present and code3_present):
                            self._debug("Multiple codes given but not present, setting HANDLED=-1 (confused)")
                            self.df.set_value(idx, 'HANDLED', -1)
                    else:
                        print("I shouldn't be here")


################################################################################
# Helper methods
################################################################################

    def get_matching_rows(self, search_term, column, skip_handled=False, blank_discipline=True):
        """Find rows that match the search_term for the given column and return indices

        Args:
            search_term (str): Term to be matched, should be full last name or full word from journal
            column (str): Matching column name from spreadsheet
            blank_discipline (bool, optional): Should matching rows have a blank discipline, default True

        Returns:
            list: List of matching indices
        """
        self._debug("Matching {}={}".format(column, search_term))
        # Get rows that have a naive match
        naive_matches = [
            idx
            for idx, row in self.df.iterrows()
            if str(search_term).lower().strip() in str(row[column]).lower()
        ]
        self._debug("Found {} naive matches for {}={}".format(len(naive_matches), column, search_term))

        if column in COL_LOOKUP.values():
            # Do a more specific match, e.g. 'Gee' should not match 'McGee' for author
            exact_matches = list()
            for idx, row in self.df.loc[naive_matches].iterrows():
                if self._match_name(row[column], search_term, column):
                    exact_matches.append(idx)

            self._debug("Found {} exact matches for '{}'".format(len(exact_matches), search_term))

            # Skip handled
            if skip_handled:
                exact_matches = list(self.df.loc[exact_matches].query("HANDLED == 0").index)
                self._debug("Found {} matches for '{}' with HANDLED=0".format(len(exact_matches), search_term))

            # Filter discipline
            if blank_discipline:
                exact_matches = list(self.df.loc[exact_matches][pd.isnull(
                    self.df.loc[exact_matches, 'DISCIPLINE'])].index)
                self._debug("Found {} matches for '{}' with empty discipline".format(len(exact_matches), search_term))

            self._debug("Found {} total rows for {}={}".format(len(exact_matches), column, search_term))
        else:
            exact_matches = naive_matches

        return exact_matches

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

                self._debug("Writing dataframe to {} with {} records".format(save_name, len(df)))
                writer = pd.ExcelWriter(save_name, engine='xlsxwriter')
                df.to_excel(writer)
                writer.save()
        else:
            save_name = self.fn
            # Specify a writer for saving
            writer = pd.ExcelWriter(save_name, engine='xlsxwriter')

            # Write dataframe to file (all sheets)
            for sheet in self.xls.sheet_names:
                self._debug("Writing sheet '{}' to {}".format(sheet, save_name))

                if sheet == self.xls.sheet_names[self.sheet_index]:
                    self.df.to_excel(writer, sheet)
                else:
                    self.xls.parse(sheet).to_excel(writer, sheet)

            # Save the result
            writer.save()

        self._print("File saved: {}".format(save_name))
        return save_name

################################################################################
# Private methods
################################################################################

    def _parse_forc_string(self, forc_string):
        match = forc_re.match(forc_string)
        if match is None:
            raise Exception("FORC_STRING not valid")

        match = forc_re.match(forc_string)
        code1 = match.group('code1')
        code1_perc = match.group('code1_perc')
        code2 = match.group('code2')
        code2_perc = match.group('code2_perc')
        code3 = match.group('code3')
        code3_perc = match.group('code3_perc')

        if code1_perc is not None:
            code1_perc = float(code1_perc)
        else:
            code1_perc = 0

        if code2_perc is not None:
            code2_perc = float(code2_perc)
        else:
            code2_perc = 0

        if code3_perc is not None:
            code3_perc = float(code3_perc)
        else:
            code3_perc = 0

        if (code1_perc == 0 and code2_perc == 0 and code3_perc == 0):
            code1_perc = 100.
            code2_perc = 0.
            code3_perc = 0.

        if code1_perc < 100:
            if (code2_perc == 0 and code3 is None):
                code2_perc = 100 - code1_perc

            if (code1_perc + code2_perc < 100 and code3_perc == 0):
                code3_perc = 100 - code1_perc - code2_perc

        if (code1_perc + code2_perc + code3_perc != 100):
            raise Exception("Percentages don't add to 100")

        return (code1, code1_perc, code2, code2_perc, code3, code3_perc,)

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
            self.xls = pd.ExcelFile(self.fn, dtype=object)
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
            self._debug("Adding HANDLED (default 0) column to spreadsheet")
            self.df['HANDLED'] = 0

        if 'DISCIPLINE' not in self.df.columns:
            self._debug("Adding DISCIPLINE (default NaN) column to spreadsheet")
            self.df['DISCIPLINE'] = np.nan

        if 'FORC_STRING' not in self.df.columns:
            self._debug("Adding FORC_STRING (default NaN) column to spreadsheet")
            self.df['FORC_STRING'] = np.nan

        # Clean some dtypes
        dtypes = {
            'ERA_18_FOR4_ClawBack_Justify': 'object',
            'ARCFORC': 'object',
            'Staff_Comments': 'object',
            'Category': 'object',
            'ARIS_UPDATED': 'object',
            'YEAR': 'int64',
            'DEPARTMENT': 'object',
            'First_MQ_Authors_Faculty': 'object',
            'AUTHORS': 'object',
            'TITLE': 'object',
            'PUBLISHER': 'object',
            'PARENT_DOC': 'object',
            'EDITOR': 'object',
            'VOL': 'object',
            'NUMB': 'object',
            'EDITION': 'object',
            'START_PAGE': 'object',
            'END_PAGE': 'object',
            'PLACE': 'object',
            'ISSBN': 'object',
            'DOI': 'object',
            'HANDLED': 'object',
            'DISCIPLINE': 'object',
        }
        for col, col_type in dtypes.items():
            self.df[col] = self.df[col].astype(col_type)

    def _print(self, msg):
        """ Simple wrapper to check verbose flag """
        if self.verbose:
            print(msg)

    def _debug(self, msg):
        """ Simple wrapper to check debug flag """
        if self.debug:
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
    parser.add_argument('--debug', action='store_true', default=False,
                        help="Show lots of output, default false")

    args = parser.parse_args()

    if not os.path.exists(args.ERAFILE):
        parser.error("File does not exist")

    # Do some argument checking
    if ((args.author and not args.forc_string) and not args.discipline):
        parser.error(
            "Setting an author discipline requires both --detect_author and -set_discipline to be set")

    if ((args.journal and not args.forc_string) and not args.discipline):
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
            (args.journal and args.discipline) or
            (args.split_disciplines and args.prefix) or
            args.carry_forward_forcs or
            args.forc_string
            ):
        parser.print_help()
        print("\nNo commands given")
        parser.exit()

    main(**vars(args))
