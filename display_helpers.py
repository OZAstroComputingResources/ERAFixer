from IPython.display import display_html, HTML, display

def show_matches(erafixer, row_match, author):
    out ='<dl>'
    for i, row_idx in enumerate(row_match.keys()):
        df_row = erafixer.df.iloc[row_idx]

        if i == 0:
            out += "<dt>Full Name</dt><dd>" + \
                erafixer.get_full_name(df_row['AUTHORS'], author).title() + '</dd>'
            out += "<dt>&nbsp;</dt><dd>&nbsp;</dd>"
            
        out += "<dt>Authors:</dt><dd>" +  df_row['AUTHORS'] + "</dd>"
    
        title = df_row['TITLE']
        out += "<dt>Title:</dt><dd>" + title + "</dd>"
        
        out += "<dt>---</dt><dd>&nbsp;</dd>"
        if i > 2:
            break
        
    out += '</dl><hr class="thick">'
    display_html(HTML(out))